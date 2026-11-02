"""Record a captioned, PostHog-branded walkthrough video of a flow on the local stack.

Run from the root of a PostHog checkout, with the stack up:

    uv run python .agents/skills/recording-demo-videos/scripts/record_demo.py storyboard.json

The storyboard format is in references/storyboard.md. The script writes the MP4, a contact sheet
of frames to review, and a log with the cut list next to the `output` path in the storyboard.
"""

import os
import re
import sys
import json
import math
import time
import base64
import shutil
import asyncio
import hashlib
import tempfile
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import layers
import requests
from PIL import Image
from playwright.async_api import BrowserContext, FloatRect, Locator, Page, async_playwright

DEFAULT_VIEWPORT = {"width": 1440, "height": 900}
FIRST_LOAD_TIMEOUT_MS = 300_000
STEP_TIMEOUT_MS = 120_000
# A wait longer than this is cut from the final video, keeping this many seconds of it.
CUT_KEEP_SECONDS = 0.3
FPS = 25
# The debug chrome of a local dev stack. It is noise in a demo.
DEFAULT_HIDE_SELECTORS = [".tricolor"]
DEFAULT_HIDE_TEXT = ["DEBUG mode"]
ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128"
# Brian, the premade ElevenLabs voice the DevEx videos use, at their settings.
DEFAULT_VOICEOVER = {
    "voice": "nPczCjzI2devNBz1zQrb",
    "model": "eleven_v3",
    "settings": {"stability": 0.5, "speed": 1.12},
}
VOICE_CACHE = Path.home() / ".cache" / "posthog-demo-videos" / "voiceover"
MUSIC_URL = "https://api.elevenlabs.io/v1/music?output_format=mp3_44100_128"
MUSIC_CACHE = Path.home() / ".cache" / "posthog-demo-videos" / "music"
DEFAULT_MUSIC_PROMPT = (
    "Light, upbeat, playful instrumental background music for a software product demo. Soft synth plucks, "
    "gentle drums, warm bass. Steady tempo, unobtrusive, no big drops."
)
# The bed sits well under the voice, and dips further while a line plays.
DEFAULT_MUSIC_VOLUME = 0.18
# Breath between a line ending and the next step starting.
VOICE_TAIL_SECONDS = 0.35
# Variables named like a credential are secret even when the storyboard does not list them in `secrets`.
SECRET_NAME = re.compile(r"(?:^|_)(?:KEY|TOKEN|SECRET|PASSWORD)$", re.IGNORECASE)
# Shorter secret values are too common to mask safely by value. The `$NAME` placeholder still hides them.
MIN_MASKED_LENGTH = 8
# PostHog's secret key formats, such as a key that a response body returns. `phc_` is public.
SECRET_TOKEN = re.compile(r"\b(ph[xshare])_[A-Za-z0-9_-]{16,}")
STICKER_POSITIONS = {
    "bottom-right": "right:56px;bottom:120px",
    "bottom-left": "left:56px;bottom:120px",
    "top-right": "right:56px;top:96px",
    "top-left": "left:56px;top:96px",
}
FALLBACK_COLORS = {
    "cobalt": "#0457FF",
    "tangerine": "#FF5C1C",
    "cream": "#F4F3EE",
    "dark": "#1D1F27",
    "green": "#47C861",
}

LOGO_JS = """
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { Logo } from "@posthog/brand/logo"
const variants = { color: { variant: "gradient" }, white: { variant: "mono", color: "#FFFFFF" } }
const out = {}
for (const [name, props] of Object.entries(variants)) {
    out[name] = renderToStaticMarkup(createElement(Logo, { ...props, size: "100%" }))
}
console.log(JSON.stringify(out))
"""


class Brand:
    """PostHog brand assets from the @posthog/brand package the frontend already depends on."""

    def __init__(self, repo_root: Path) -> None:
        self.package = repo_root / "frontend" / "node_modules" / "@posthog" / "brand" / "dist"
        self.available = self.package.exists()
        self.colors = dict(FALLBACK_COLORS)
        self.font_css = ""
        self.logos = {"color": "", "white": ""}
        if not self.available:
            sys.stderr.write("warning: @posthog/brand not found, run pnpm install. Using fallback styling.\n")
            return
        self._load_colors()
        self._load_fonts()
        self._load_logos(repo_root / "frontend")

    def _load_colors(self) -> None:
        source = (self.package / "generated" / "colors" / "css.mjs").read_text()
        match = re.search(r'const colorsCss = ("(?:[^"\\]|\\.)*")', source)
        if not match:
            return
        css = json.loads(match.group(1))
        for name, value in re.findall(r"--posthog-([a-z-]+):\s*(#[0-9A-Fa-f]{6})", css):
            self.colors[name] = value
        self.colors.setdefault("cream", FALLBACK_COLORS["cream"])
        self.colors.setdefault("dark", FALLBACK_COLORS["dark"])

    def _load_fonts(self) -> None:
        faces = {500: "RoundHog-Medium.woff2", 700: "RoundHog-SemiBold.woff2", 800: "RoundHog-Bold.woff2"}
        rules = []
        for weight, filename in faces.items():
            path = self.package / "fonts" / filename
            if path.exists():
                data = base64.b64encode(path.read_bytes()).decode()
                rules.append(
                    f'@font-face{{font-family:"RoundHog";font-weight:{weight};font-style:normal;'
                    f'src:url(data:font/woff2;base64,{data}) format("woff2")}}'
                )
        self.font_css = "\n".join(rules)

    def _load_logos(self, frontend: Path) -> None:
        try:
            result = subprocess.run(
                ["node", "--input-type=module", "-e", LOGO_JS],
                cwd=frontend,
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )
            self.logos = json.loads(result.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as error:
            sys.stderr.write(f"warning: could not render the logo ({error}). Cards go without it.\n")

    def hog(self, slug: str | None) -> str:
        if not slug or not self.available:
            return ""
        path = self.package / "generated" / "hoggies" / "png" / f"{slug}.png"
        if not path.exists():
            options = sorted(p.stem for p in path.parent.glob("*.png"))
            raise SystemExit(f'Unknown hog "{slug}". Pick one of: {", ".join(options)}')
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def overlay_script(brand: Brand, hide_selectors: list[str], hide_text: list[str]) -> str:
    """The caption bar, the cursor and the chrome hider, injected into every page of the recording."""
    config = {
        "fontCss": brand.font_css,
        "dark": brand.colors["dark"],
        "cream": brand.colors["cream"],
        "accent": brand.colors["tangerine"],
        "hideSelectors": hide_selectors,
        "hideText": hide_text,
    }
    return (
        "(() => { if (window.top !== window) return; const C = "
        + json.dumps(config)
        + r""";
  // Hidden from the first frame of every page, before the app renders them.
  if (C.hideSelectors.length) {
    const early = document.createElement('style');
    early.textContent = C.hideSelectors.join(',') + '{display:none!important}';
    // The root element can be missing this early in a load. A failure here would stop the whole overlay.
    const attach = () => { if (!document.documentElement) return false; document.documentElement.appendChild(early); return true; };
    if (!attach()) { const watch = new MutationObserver(() => { if (attach()) watch.disconnect(); }); watch.observe(document, { childList: true }); }
  }
  const ensure = () => {
    if (!document.body || document.getElementById('__demo_cursor')) return;
    if (C.fontCss) { const s = document.createElement('style'); s.textContent = C.fontCss; document.head.appendChild(s); }
    // A pointer arrow drawn larger than life, so it reads in a scaled-down video. The tip is the hotspot.
    const cursor = document.createElement('div'); cursor.id = '__demo_cursor';
    cursor.style.cssText = 'position:fixed;left:0;top:0;width:34px;height:34px;margin:-3px 0 0 -6px;z-index:2147483647;'
      + 'pointer-events:none;transform-origin:6px 3px;transition:transform .08s;transform:translate(-100px,-100px)';
    cursor.innerHTML = '<svg viewBox="0 0 24 24" width="34" height="34" style="filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))">'
      + '<path d="M5.5 3.2v16.1l4.2-4.1 2.7 6.2 2.6-1.1-2.7-6.1h5.9z" fill="#111" stroke="#fff" stroke-width="1.6" '
      + 'stroke-linejoin="round"/></svg>';
    document.body.appendChild(cursor);
    const cap = document.createElement('div'); cap.id = '__demo_caption';
    cap.style.cssText = 'position:fixed;left:50%;bottom:32px;transform:translateX(-50%);max-width:1080px;padding:14px 24px;'
      + 'border-radius:10px;border-left:6px solid ' + C.accent + ';background:' + C.dark + 'ee;color:' + C.cream + ';'
      + 'font:700 21px/1.35 RoundHog,-apple-system,Inter,sans-serif;z-index:2147483646;pointer-events:none;'
      + 'text-align:left;box-shadow:0 10px 30px rgba(0,0,0,.25);display:none';
    document.body.appendChild(cap);
    let x = window.__demoCursorAt ? window.__demoCursorAt[0] : -100;
    let y = window.__demoCursorAt ? window.__demoCursorAt[1] : -100;
    let s = 1;
    const paint = () => { cursor.style.transform = `translate(${x}px,${y}px) scale(${s})`; };
    paint();
    window.__demoMoveCursor = (nx, ny) => { x = nx; y = ny; paint(); };
    window.__demoClick = (cx, cy) => {
      s = 0.85; paint(); setTimeout(() => { s = 1; paint(); }, 140);
      const ring = document.createElement('div');
      ring.style.cssText = 'position:fixed;left:' + cx + 'px;top:' + cy + 'px;width:40px;height:40px;'
        + 'margin:-20px 0 0 -20px;border-radius:50%;border:3px solid ' + C.accent + ';z-index:2147483646;pointer-events:none;'
        + 'transform:scale(.3);opacity:.9;transition:transform .45s ease-out,opacity .45s ease-out';
      document.body.appendChild(ring);
      requestAnimationFrame(() => requestAnimationFrame(() => { ring.style.transform = 'scale(1.4)'; ring.style.opacity = '0'; }));
      setTimeout(() => ring.remove(), 500);
    };
  };
  const hide = () => {
    for (const sel of C.hideSelectors) document.querySelectorAll(sel).forEach(el => { el.style.display = 'none'; });
    if (!C.hideText.length) return;
    for (const el of document.querySelectorAll('div,section,aside,header,footer')) {
      const t = (el.textContent || '').trim();
      for (const text of C.hideText) {
        const parent = el.parentElement ? (el.parentElement.textContent || '').trim() : '';
        if (t.startsWith(text) && t.length < text.length + 120 && parent.length >= text.length + 120) el.style.display = 'none';
      }
    }
  };
  window.__sticker = (src, label, pos, seconds) => {
    ensure();
    const el = document.createElement('div');
    el.style.cssText = 'position:fixed;' + pos + ';z-index:2147483645;pointer-events:none;display:flex;flex-direction:column;'
      + 'align-items:center;gap:6px;transform:scale(.2) rotate(-14deg);opacity:0;'
      + 'transition:transform .42s cubic-bezier(.34,1.7,.5,1),opacity .2s';
    el.innerHTML = '<img src="' + src + '" style="width:190px;height:190px;object-fit:contain;filter:drop-shadow(0 8px 14px rgba(0,0,0,.22))">'
      + (label ? '<div style="background:' + C.accent + ';color:#fff;font:800 22px RoundHog,-apple-system,sans-serif;'
      + 'padding:6px 16px;border-radius:999px;transform:rotate(-4deg);box-shadow:0 6px 16px rgba(0,0,0,.2)"></div>' : '');
    if (label) el.lastChild.textContent = label;
    document.body.appendChild(el);
    requestAnimationFrame(() => requestAnimationFrame(() => { el.style.opacity = '1'; el.style.transform = 'scale(1) rotate(5deg)'; }));
    setTimeout(() => { el.style.transition = 'transform .3s ease-in,opacity .3s'; el.style.opacity = '0';
      el.style.transform = 'scale(.6) rotate(12deg)'; setTimeout(() => el.remove(), 400); }, seconds * 1000);
  };
  window.__caption = (t) => { ensure(); const el = document.getElementById('__demo_caption'); if (!el) return;
    el.textContent = t || ''; el.style.display = t ? 'block' : 'none'; };
  document.addEventListener('DOMContentLoaded', ensure);
  setInterval(() => { ensure(); hide(); }, 300);
})();"""
    )


def card_html(brand: Brand, heading: str, subheading: str, hog: str, dark: bool = False) -> str:
    bg = brand.colors["dark"] if dark else brand.colors["cream"]
    fg = brand.colors["cream"] if dark else brand.colors["dark"]
    logo = brand.logos.get("white" if dark else "color", "")
    hog_img = f'<img src="{hog}" style="width:340px;height:340px;object-fit:contain">' if hog else ""
    return f"""<!doctype html><html><head><style>{brand.font_css}
#__demo_cursor{{display:none!important}}
body{{margin:0;height:100vh;background:{bg};color:{fg};font-family:RoundHog,-apple-system,Inter,sans-serif;
display:flex;align-items:center;justify-content:center;overflow:hidden}}
.logo{{position:absolute;top:44px;left:56px;width:180px}}
.wrap{{display:flex;align-items:center;gap:64px;max-width:1180px;padding:0 80px}}
h1{{font-weight:800;font-size:64px;line-height:1.05;margin:0 0 20px}}
p{{font-weight:500;font-size:28px;line-height:1.35;margin:0;opacity:.8}}
.bar{{width:72px;height:8px;border-radius:4px;background:{brand.colors["tangerine"]};margin-bottom:28px}}
</style></head><body><div class="logo">{logo}</div><div class="wrap"><div><div class="bar"></div>
<h1>{escape(heading)}</h1><p>{escape(subheading)}</p></div>{hog_img}</div></body></html>"""


def terminal_html(brand: Brand, title: str) -> str:
    return f"""<!doctype html><html><head><style>{brand.font_css}
#__demo_cursor{{display:none!important}}
body{{margin:0;height:100vh;background:{brand.colors["dark"]};color:#d4d4d4;font:17px/1.6 Menlo,Consolas,monospace}}
.logo{{position:absolute;top:36px;right:48px;width:140px;opacity:.9}}
.title{{font:700 26px RoundHog,-apple-system,sans-serif;color:{brand.colors["cream"]};margin-bottom:24px}}
pre{{white-space:pre-wrap;margin:0}} #out{{margin-top:24px;color:{brand.colors["green"]}}}
#out.bad{{color:{brand.colors.get("coral", "#FF474D")}}}
</style></head><body><div class="logo">{brand.logos.get("white", "")}</div>
<div style="padding:56px 64px"><div class="title">{escape(title)}</div><pre id="cmd"></pre><pre id="out"></pre></div></body></html>"""


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Vars:
    """`${NAME}` substitution. Secret values are used for requests but shown as `$NAME`.

    Shown text is also masked by value, so a secret that reaches it another way, such as in a
    response body or an unlisted variable named like a key, still never appears in the video.
    """

    def __init__(self, values: dict[str, str], secrets: list[str]) -> None:
        self.values = values
        self.secrets = set(secrets) | {name for name in values if SECRET_NAME.search(name)}
        masks = [(values[name], name) for name in self.secrets if len(values.get(name, "")) >= MIN_MASKED_LENGTH]
        # Longest first, so a secret that contains another one is masked whole.
        self.masks = sorted(masks, key=lambda mask: -len(mask[0]))

    def real(self, value: Any) -> Any:
        return self._walk(value, show=False)

    def shown(self, value: Any) -> Any:
        return self._walk(value, show=True)

    def mask(self, text: str) -> str:
        for secret, name in self.masks:
            text = text.replace(secret, f"${name}")
        return SECRET_TOKEN.sub(lambda m: f"{m.group(1)}_********", text)

    def _walk(self, value: Any, show: bool) -> Any:
        if isinstance(value, str):
            text = re.sub(r"\$\{(\w+)\}", lambda m: self._one(m.group(1), show), value)
            return self.mask(text) if show else text
        if isinstance(value, list):
            return [self._walk(v, show) for v in value]
        if isinstance(value, dict):
            return {k: self._walk(v, show) for k, v in value.items()}
        return value

    def _one(self, name: str, show: bool) -> str:
        if show and name in self.secrets:
            return f"${name}"
        if name not in self.values:
            raise SystemExit(f"Storyboard uses ${{{name}}} but it is not in vars or the environment.")
        return self.values[name]


def elevenlabs_post(url: str, body: dict[str, Any], timeout: int) -> bytes:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise SystemExit("Music and voiceover need ELEVENLABS_API_KEY in the environment.")
    try:
        response = requests.post(url, json=body, headers={"xi-api-key": api_key}, timeout=timeout)
    except requests.RequestException as error:
        raise SystemExit(f"Could not reach ElevenLabs: {error}") from error
    if not response.ok:
        raise SystemExit(f"ElevenLabs returned {response.status_code}: {response.text[:400]}")
    return response.content


class Voiceover:
    """One ElevenLabs take of every spoken line, cut back into a clip per line.

    The whole script is read as one take, so the delivery flows instead of restarting on each line.
    The per-character timestamps from ElevenLabs cut it per line. Takes are cached by text and voice,
    so recording again with the same script costs no credits.
    """

    def __init__(self, config: dict[str, Any], lines: dict[str, str], workdir: Path) -> None:
        self.config = {**DEFAULT_VOICEOVER, **config}
        self.lines = {key: text for key, text in lines.items() if text.strip()}
        self.clips: dict[str, tuple[Path, float]] = {}
        if self.lines:
            self._prepare(workdir)

    def _prepare(self, workdir: Path) -> None:
        keys = list(self.lines)
        text = "\n\n".join(self.lines[key] for key in keys)
        mp3, alignment = self._take(text)
        chars = alignment["characters"]
        starts, ends = alignment["character_start_times_seconds"], alignment["character_end_times_seconds"]
        spoken = "".join(chars)
        cursor = 0
        for key in keys:
            at = spoken.find(self.lines[key], cursor)
            if at < 0:
                raise SystemExit(f"The voiceover take does not contain the line for {key}.")
            end = at + len(self.lines[key]) - 1
            cursor = end + 1
            begin, finish = max(starts[at] - 0.05, 0), ends[end] + 0.1
            clip = workdir / f"voice-{key}.wav"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(mp3),
                    "-ss",
                    f"{begin:.3f}",
                    "-to",
                    f"{finish:.3f}",
                    str(clip),
                ],
                check=True,
            )
            self.clips[key] = (clip, finish - begin)

    def _take(self, text: str) -> tuple[Path, dict[str, Any]]:
        key = hashlib.sha256(json.dumps([text, self.config], sort_keys=True).encode()).hexdigest()[:20]
        mp3, timing = VOICE_CACHE / f"{key}.mp3", VOICE_CACHE / f"{key}.json"
        if mp3.exists() and timing.exists():
            return mp3, json.loads(timing.read_text())
        body = {"text": text, "model_id": self.config["model"], "voice_settings": self.config.get("settings", {})}
        data = json.loads(elevenlabs_post(ELEVEN_URL.format(voice=self.config["voice"]), body, timeout=300))
        VOICE_CACHE.mkdir(parents=True, exist_ok=True)
        mp3.write_bytes(base64.b64decode(data["audio_base64"]))
        # Written last, so a half-written take never counts as cached.
        timing.write_text(json.dumps(data["alignment"]))
        return mp3, data["alignment"]


def spoken_lines(storyboard: dict[str, Any], variables: "Vars") -> dict[str, str]:
    """What the voiceover says, keyed by where it is said. A `say` key wins over the caption or card text."""

    def card_line(spec: dict[str, Any]) -> str:
        if "say" in spec:
            return spec["say"]
        return " ".join(part.rstrip(".") + "." for part in (spec.get("heading"), spec.get("subheading")) if part)

    lines: dict[str, str] = {}
    if "title" in storyboard:
        lines["title"] = card_line(storyboard["title"])
    for index, step in enumerate(storyboard["steps"]):
        if "card" in step:
            lines[f"step{index}"] = card_line(step["card"])
        elif "http" in step:
            lines[f"step{index}"] = step["http"].get("say", step["http"].get("title", ""))
        else:
            lines[f"step{index}"] = step.get("say", step.get("caption", ""))
    if "end" in storyboard:
        lines["end"] = card_line(storyboard["end"])
    return {key: variables.shown(text) for key, text in lines.items()}


class Recorder:
    def __init__(self, storyboard: dict[str, Any], brand: Brand, variables: Vars) -> None:
        self.sb = storyboard
        self.brand = brand
        self.vars = variables
        self.base_url = storyboard.get("base_url", "http://localhost:8010").rstrip("/")
        self.cuts: list[tuple[float, float]] = []
        self.t0 = 0.0
        self.voice: Voiceover | None = None
        # Sounds to lay over the video: (seconds into the cut video, file).
        self.sounds: list[tuple[float, Path]] = []
        self.speaking_until = 0.0
        self.pop: Path | None = None
        self.voice_log: list[dict[str, Any]] = []
        self.base = Path(".")
        self.mouse: tuple[float, float] = (720.0, 450.0)
        # With a zoom in the storyboard, captions and stickers are drawn after the camera pass, so they don't zoom.
        self.layered = any("zoom" in step for step in storyboard["steps"])
        self.timeline: dict[str, list[dict[str, Any]]] = {"captions": [], "stickers": [], "cards": [], "zooms": []}
        self.last_box: FloatRect | None = None

    def now(self) -> float:
        return time.monotonic() - self.t0

    def video_now(self) -> float:
        """Seconds into the final video, after the cuts made so far."""
        return self.now() - sum(end - start for start, end in self.cuts)

    def speak(self, key: str) -> None:
        if not self.voice or key not in self.voice.clips:
            return
        clip, duration = self.voice.clips[key]
        self.sounds.append((self.video_now(), clip))
        self.voice_log.append({"line": key, "at": round(self.video_now(), 2), "seconds": round(duration, 2)})
        self.speaking_until = self.video_now() + duration + VOICE_TAIL_SECONDS

    async def finish_speaking(self) -> None:
        # Cuts made while a line plays shorten the video, so this waits on video time, not wall time.
        while self.video_now() < self.speaking_until:
            await asyncio.sleep(0.1)

    async def sticker(self, page: Page, spec: dict[str, Any]) -> None:
        if self.layered:
            self.timeline["stickers"].append({**spec, "at": self.now(), "text": self.vars.shown(spec.get("text", ""))})
            if self.pop:
                self.sounds.append((self.video_now() + 0.05, self.pop))
            return
        position = STICKER_POSITIONS.get(spec.get("position", "bottom-right"), STICKER_POSITIONS["bottom-right"])
        await page.evaluate(
            "([src, label, pos, seconds]) => window.__sticker && window.__sticker(src, label, pos, seconds)",
            [
                self.brand.hog(spec.get("hog", "star")),
                self.vars.shown(spec.get("text", "")),
                position,
                spec.get("seconds", 3),
            ],
        )
        if self.pop:
            self.sounds.append((self.video_now() + 0.05, self.pop))

    async def show(self, page: Page, html: str) -> None:
        await page.set_content(html)
        await page.evaluate(
            "document.fonts.ready.then(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))"
        )

    async def waited(self, coro: Any, keep: float = CUT_KEEP_SECONDS, shortest: float = 0.4, tail: float = 0.2) -> None:
        start = self.now()
        await coro
        end = self.now()
        if end - start > keep + shortest:
            self.cuts.append((round(start + keep, 2), round(end - tail, 2)))

    def url(self, path: str) -> str:
        path = self.vars.real(path)
        return path if path.startswith("http") else f"{self.base_url}{path}"

    def locate(self, page: Page, target: dict[str, Any]) -> Locator:
        target = self.vars.real(target)
        scope = page.locator(target["within"]) if "within" in target else page.locator("body")
        if "selector" in target:
            loc = scope.locator(target["selector"])
        elif "role" in target:
            loc = scope.get_by_role(target["role"], name=target.get("name"), exact=True)
        elif "label" in target:
            loc = scope.get_by_label(target["label"], exact=True)
        elif "text" in target:
            loc = scope.get_by_text(target["text"], exact=target.get("exact", False))
        else:
            raise SystemExit(f"Target needs selector, role, label or text: {target}")
        return loc.nth(target.get("nth", 0))

    async def caption(self, page: Page, text: str) -> None:
        if self.layered:
            self.timeline["captions"].append({"at": self.now(), "text": self.vars.shown(text)})
            return
        await page.evaluate("t => window.__caption && window.__caption(t)", self.vars.shown(text))

    async def glide(self, page: Page, loc: Locator) -> None:
        await loc.wait_for(state="visible", timeout=STEP_TIMEOUT_MS)
        await loc.scroll_into_view_if_needed()
        box = await loc.bounding_box()
        self.last_box = box
        if box:
            await self.move_mouse(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            await asyncio.sleep(0.2)

    async def move_mouse(self, page: Page, x: float, y: float) -> None:
        # Ease in and out along a slight arc, over a time that grows with the distance, like a hand moves.
        x0, y0 = self.mouse
        distance = math.hypot(x - x0, y - y0)
        frames = max(8, min(36, int(distance / 28)))
        bend = min(distance * 0.08, 40)
        for i in range(1, frames + 1):
            t = i / frames
            eased = 4 * t**3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2
            arc = math.sin(math.pi * eased) * bend
            await page.mouse.move(x0 + (x - x0) * eased, y0 + (y - y0) * eased - arc)
            await page.evaluate(
                "([x, y]) => window.__demoMoveCursor && window.__demoMoveCursor(x, y)",
                [x0 + (x - x0) * eased, y0 + (y - y0) * eased - arc],
            )
            await asyncio.sleep(1 / FPS)
        self.mouse = (x, y)

    async def click_effect(self, page: Page) -> None:
        await page.evaluate("([x, y]) => window.__demoClick && window.__demoClick(x, y)", list(self.mouse))

    async def restore_cursor(self, page: Page) -> None:
        # A new page starts without a pointer. Put it back where it was, so it does not jump in from a corner.
        x, y = self.mouse
        await page.evaluate(
            "([x, y]) => { window.__demoCursorAt = [x, y]; window.__demoMoveCursor && window.__demoMoveCursor(x, y); }",
            [x, y],
        )

    async def log_in(self, context: BrowserContext) -> None:
        login = self.sb.get("login", {"email": "test@posthog.com", "password": "12345678"})
        page = await context.new_page()
        await page.goto(f"{self.base_url}/login", timeout=FIRST_LOAD_TIMEOUT_MS)
        status = await page.evaluate(
            """async ({email, password}) => (await fetch('/api/login/', {method: 'POST',
                headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email, password})})).status""",
            self.vars.real(login),
        )
        if status != 200:
            raise SystemExit(f"Login returned {status}. Check `login` in the storyboard.")
        # The dev server compiles each chunk on its first request. Loading every page once here keeps
        # the recording from showing minutes of spinners.
        for step in self.sb["steps"]:
            if "goto" in step and self.url(step["goto"]).startswith(self.base_url):
                await page.goto(self.url(step["goto"]), timeout=FIRST_LOAD_TIMEOUT_MS)
                await page.wait_for_timeout(5000)
        await page.close()

    async def card(self, page: Page, spec: dict[str, Any], key: str, dark: bool = False) -> None:
        start = self.now()
        await self._card(page, spec, key, dark)
        self.timeline["cards"].append({"from": start, "to": self.now()})

    async def _card(self, page: Page, spec: dict[str, Any], key: str, dark: bool = False) -> None:
        html = card_html(
            self.brand,
            self.vars.shown(spec.get("heading", "")),
            self.vars.shown(spec.get("subheading", "")),
            self.brand.hog(spec.get("hog")),
            dark=dark,
        )
        # The video runs a little behind the clock, so the cut runs past the moment the card is ready.
        await self.waited(self.show(page, html), keep=0, shortest=0.05, tail=-0.3)
        self.speak(key)
        await asyncio.sleep(spec.get("hold", 1.0 if self.voice else 2.5))
        await self.finish_speaking()

    async def http(self, page: Page, spec: dict[str, Any], key: str) -> None:
        start = self.now()
        await self._http(page, spec, key)
        self.timeline["cards"].append({"from": start, "to": self.now()})

    async def _http(self, page: Page, spec: dict[str, Any], key: str) -> None:
        method = spec.get("method", "POST").upper()
        shown_url, real_url = self.url(self.vars.shown(spec["url"])), self.url(spec["url"])
        headers = spec.get("headers", {})
        body = spec.get("json")
        lines = [f"$ curl -X {method} {shown_url} \\"]
        for name, value in self.vars.shown(headers).items():
            lines.append(f'    -H "{name}: {value}" \\')
        if body is not None:
            lines.append('    -H "Content-Type: application/json" \\')
            lines.append(f"    -d '{json.dumps(self.vars.shown(body), indent=2)}'")
        command = "\n".join(lines).rstrip(" \\")
        await self.waited(
            self.show(page, terminal_html(self.brand, self.vars.shown(spec.get("title", "")))),
            keep=0,
            shortest=0.05,
            tail=-0.3,
        )
        self.speak(key)
        await page.evaluate(
            """async (t) => { const el = document.getElementById('cmd');
               for (let i = 0; i < t.length; i += 3) { el.textContent = t.slice(0, i + 3); await new Promise(r => setTimeout(r, 12)); } }""",
            command,
        )
        await asyncio.sleep(0.5)
        response = requests.request(
            method,
            real_url,
            json=self.vars.real(body) if body is not None else None,
            headers=self.vars.real(headers),
            timeout=60,
        )
        status, raw = response.status_code, response.content
        try:
            text = json.dumps(json.loads(raw), indent=2)
        except ValueError:
            text = raw.decode(errors="replace")[:1500]
        text = self.vars.mask(text)
        await page.evaluate(
            "([t, bad]) => { const el = document.getElementById('out'); el.textContent = t; if (bad) el.className = 'bad'; }",
            [f"HTTP {status}\n{text}", status >= 400],
        )
        expected = spec.get("expect_status")
        if expected and status != expected:
            raise RuntimeError(f"{method} {shown_url} returned {status}, expected {expected}: {text[:300]}")
        await asyncio.sleep(spec.get("hold", 1.5 if self.voice else 3))
        await self.finish_speaking()

    async def load(self, page: Page, step: dict[str, Any]) -> None:
        await page.goto(self.url(step["goto"]), timeout=FIRST_LOAD_TIMEOUT_MS)
        if "wait_for" in step:
            await self.locate(page, step["wait_for"]).wait_for(timeout=STEP_TIMEOUT_MS)

    async def step(self, page: Page, step: dict[str, Any], key: str) -> None:
        if "card" in step:
            await self.card(page, step["card"], key)
            return
        if "http" in step:
            await self.http(page, step["http"], key)
            return
        if "goto" in step:
            await self.waited(self.load(page, step), keep=0)
            await self.restore_cursor(page)
        if "caption" in step:
            await self.caption(page, step["caption"])
        self.speak(key)
        self.last_box = None
        acting = self.now()
        if "scroll" in step:
            await page.mouse.wheel(0, step["scroll"])
            await asyncio.sleep(0.6)
        if "hover" in step:
            await self.glide(page, self.locate(page, step["hover"]))
        if "click" in step:
            loc = self.locate(page, step["click"])
            await self.glide(page, loc)
            await self.click_effect(page)
            await loc.click()
        if "type" in step:
            spec = step["type"]
            if "target" in spec:
                loc = self.locate(page, spec["target"])
                await self.glide(page, loc)
                await self.click_effect(page)
                await loc.click()
            for key in spec.get("keys", []):
                name, _, times = key.partition(" x")
                for _ in range(int(times or 1)):
                    await page.keyboard.press(name)
            await page.keyboard.type(self.vars.real(spec.get("text", "")), delay=spec.get("delay_ms", 80))
        acted = self.now()
        if "wait_for" in step and "goto" not in step:
            await self.waited(self.locate(page, step["wait_for"]).wait_for(timeout=STEP_TIMEOUT_MS))
        zoom = step.get("zoom")
        detail = None
        if zoom is True and self.last_box:
            box, until = self.last_box, acted + layers.ZOOM_AFTER_ACTION
            self.timeline["zooms"].append({"from": acting, "to": until, "box": box, "level": None})
        elif isinstance(zoom, dict) and "target" in zoom:
            target = self.locate(page, zoom["target"])
            await self.waited(target.wait_for(state="visible", timeout=STEP_TIMEOUT_MS))
            detail = {"from": self.now(), "box": await target.bounding_box(), "level": zoom.get("level")}
        if "sticker" in step:
            await self.sticker(page, step["sticker"])
        default_hold = 0.5 if self.voice else max(1.5, len(step.get("caption", "").split()) * 0.25)
        await asyncio.sleep(step.get("hold", default_hold))
        await self.finish_speaking()
        if detail and detail["box"]:
            self.timeline["zooms"].append({**detail, "to": self.now()})

    async def run(self, output: Path) -> dict[str, Any]:
        viewport = self.sb.get("viewport", DEFAULT_VIEWPORT)
        video_dir = Path(tempfile.mkdtemp(prefix="demo-video-"))
        log: dict[str, Any] = {"output": str(output)}
        if "voiceover" in self.sb:
            self.voice = Voiceover(self.sb["voiceover"], spoken_lines(self.sb, self.vars), video_dir)
        if any("sticker" in step for step in self.sb["steps"]):
            self.pop = pop_sound(video_dir)
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            setup = await browser.new_context(viewport=viewport)
            await self.log_in(setup)
            state = await setup.storage_state()
            await setup.close()
            context = await browser.new_context(
                viewport=viewport,
                storage_state=state,
                # Cards and the overlay are inline HTML, which the app's Content Security Policy refuses.
                bypass_csp=True,
                record_video_dir=str(video_dir),
                record_video_size=viewport,
            )
            await context.add_init_script(
                overlay_script(
                    self.brand,
                    DEFAULT_HIDE_SELECTORS + self.sb.get("hide_selectors", []),
                    DEFAULT_HIDE_TEXT + self.sb.get("hide_text", []),
                )
            )
            page = await context.new_page()
            self.t0 = time.monotonic()
            try:
                if "title" in self.sb:
                    await self.card(page, self.sb["title"], "title")
                for index, step in enumerate(self.sb["steps"]):
                    log["step"] = index
                    await self.step(page, step, f"step{index}")
                await self.caption(page, "")
                if "end" in self.sb:
                    await self.card(page, self.sb["end"], "end")
                # The recording drops its last frames when the context closes.
                await asyncio.sleep(1.5)
                log["duration"] = round(self.now(), 2)
            except Exception as error:
                log["error"] = self.vars.mask(f"step {log.get('step')}: {error!r}")[:800]
                await page.screenshot(path=str(output.with_suffix(".error.png")))
            finally:
                raw_video = Path(await page.video.path()) if page.video else None
                await context.close()
                await browser.close()
        log["cuts"] = self.cuts
        if self.voice_log:
            log["voice"] = self.voice_log
        if raw_video and "error" not in log:
            source, cuts, duration = raw_video, self.cuts, log["duration"]
            if self.layered:
                # The camera and overlay pass cuts the video itself, so the encode below only adds the sound.
                source = output.with_suffix(".camera.mp4")
                frames = _kept_frames(raw_video, self.cuts, duration, viewport)
                # The overlay pass renders with Playwright's sync API, which can't run inside this event loop.
                await asyncio.to_thread(
                    layers.compose,
                    sys.modules[__name__],
                    self.brand,
                    frames,
                    self.timeline,
                    viewport,
                    viewport["width"],
                    FPS,
                    source,
                )
                cuts, duration = [], duration_of(source)
                log["zooms"] = len(self.timeline["zooms"])
            encode(
                source,
                output,
                cuts,
                duration,
                self.sounds,
                self.sb["music"] if "music" in self.sb else None,
                self.base,
            )
            if source != raw_video:
                source.unlink()
            contact_sheet(output)
        elif raw_video:
            shutil.copy(raw_video, output.with_suffix(".failed.webm"))
        shutil.rmtree(video_dir, ignore_errors=True)
        return log


def _kept_frames(
    raw: Path, cuts: list[tuple[float, float]], duration: float, viewport: dict[str, int]
) -> Iterator[tuple[float, Image.Image]]:
    """The frames of the raw take that stay in the video, with their time on the recording clock."""
    width, height = viewport["width"], viewport["height"]
    decode = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-i", str(raw), "-vf", f"fps={FPS},scale={width}:{height}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE,
    )  # fmt: skip
    assert decode.stdout is not None
    size = width * height * 3
    index = 0
    while chunk := decode.stdout.read(size):
        if len(chunk) < size:
            break
        t = index / FPS
        index += 1
        if t > duration + 0.5:
            break
        if not any(start <= t <= end for start, end in cuts):
            yield t, Image.frombytes("RGB", (width, height), chunk)
    decode.stdout.close()
    decode.wait()


def music_track(spec: dict[str, Any], seconds: float, base: Path) -> Path:
    """A music bed at least `seconds` long: a file from the storyboard, or one generated by ElevenLabs Music."""
    if "file" in spec:
        return (base / spec["file"]).resolve()
    prompt = spec.get("prompt", DEFAULT_MUSIC_PROMPT)
    # Generated in 10 second steps, so a slightly longer take reuses the cached track.
    length_ms = min(max(int((seconds + 9.99) // 10 * 10_000), 10_000), 300_000)
    key = hashlib.sha256(json.dumps([prompt, length_ms]).encode()).hexdigest()[:20]
    path = MUSIC_CACHE / f"{key}.mp3"
    if not path.exists():
        audio = elevenlabs_post(
            MUSIC_URL, {"prompt": prompt, "music_length_ms": length_ms, "force_instrumental": True}, timeout=600
        )
        MUSIC_CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
    return path


def duration_of(path: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return float(probe.stdout.strip())


def encode(
    raw: Path,
    output: Path,
    cuts: list[tuple[float, float]],
    duration: float,
    sounds: list[tuple[float, Path]],
    music: dict[str, Any] | None,
    base: Path,
) -> None:
    keep = f"between(t,0,{duration + 0.5})"
    if cuts:
        keep += "*not(" + "+".join(f"between(t,{a},{b})" for a, b in cuts) + ")"
    silent = output.with_suffix(".silent.mp4") if sounds or music is not None else output
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
            "-vf", f"fps={FPS},select='{keep}',setpts=N/{FPS}/TB",
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "22",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(silent),
        ],
        check=True,
    )  # fmt: skip
    if not sounds and music is None:
        return
    inputs: list[str] = []
    chains: list[str] = []
    for index, (at, path) in enumerate(sounds, start=1):
        inputs += ["-i", str(path)]
        delay = max(int(at * 1000), 0)
        chains.append(f"[{index}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={delay}|{delay}[s{index}]")
    if sounds:
        mix = "".join(f"[s{i}]" for i in range(1, len(sounds) + 1))
        chains.append(f"{mix}amix=inputs={len(sounds)}:normalize=0:dropout_transition=0[front]")
    if music is not None:
        length = duration_of(silent)
        inputs += ["-stream_loop", "-1", "-i", str(music_track(music, length, base))]
        volume = music.get("volume", DEFAULT_MUSIC_VOLUME)
        fade_out = max(length - 2.5, 0)
        chains.append(
            f"[{len(sounds) + 1}:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{length:.2f},"
            f"volume={volume},afade=t=in:d=1.5,afade=t=out:st={fade_out:.2f}:d=2.5[bed]"
        )
        if sounds:
            # The bed ducks under the voice and sound effects, then comes back up between lines.
            chains.append("[front]asplit=2[front_mix][front_key]")
            chains.append("[bed][front_key]sidechaincompress=threshold=0.02:ratio=6:attack=30:release=400[ducked]")
            chains.append("[front_mix][ducked]amix=inputs=2:normalize=0:dropout_transition=0[mixed]")
        else:
            chains.append("[bed]anull[mixed]")
    else:
        chains.append("[front]anull[mixed]")
    # -16 LUFS, the usual level for web video, so it plays as loud as other videos in Slack or Loom.
    # apad keeps the audio running to the end of the video, so -shortest never cuts the video short.
    chains.append("[mixed]loudnorm=I=-16:TP=-1.5:LRA=11,apad[aout]")
    graph = ";".join(chains)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), *inputs,
            "-filter_complex", graph, "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(output),
        ],
        check=True,
    )  # fmt: skip
    silent.unlink()


def pop_sound(workdir: Path) -> Path:
    """A short rising blip for stickers, synthesized so the skill ships no audio files."""
    path = workdir / "pop.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
            "-i", "aevalsrc='0.4*sin(2*PI*(420+2600*t)*t)*exp(-16*t)':s=44100:d=0.22",
            "-ac", "2", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def contact_sheet(video: Path) -> None:
    every = max(duration_of(video) / 16, 0.5)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
            "-vf", f"fps=1/{every:.2f},scale=480:-1,tile=4x4", "-frames:v", "1",
            str(video.with_suffix(".sheet.png")),
        ],
        check=True,
    )  # fmt: skip


def without_elevenlabs(storyboard: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop the voiceover and generated music, so a developer without an ElevenLabs key still gets a captioned video."""
    skipped = []
    if "voiceover" in storyboard:
        skipped.append("voiceover")
    if "music" in storyboard and "file" not in storyboard["music"]:
        skipped.append("music")
    return {name: value for name, value in storyboard.items() if name not in skipped}, skipped


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is missing. Install it first (apt-get install -y ffmpeg, or brew install ffmpeg).")
    storyboard_path = Path(sys.argv[1]).resolve()
    storyboard = json.loads(storyboard_path.read_text())
    skipped: list[str] = []
    if not os.environ.get("ELEVENLABS_API_KEY"):
        storyboard, skipped = without_elevenlabs(storyboard)
    repo_root = Path(
        subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() or "."
    )
    output = (storyboard_path.parent / storyboard.get("output", "demo.mp4")).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    values = {**os.environ, **storyboard.get("vars", {})}
    variables = Vars(values, storyboard.get("secrets", []))
    brand = Brand(repo_root)
    recorder = Recorder(storyboard, brand, variables)
    recorder.base = storyboard_path.parent
    log = asyncio.run(recorder.run(output))
    if skipped:
        log["skipped_without_elevenlabs_key"] = skipped
    output.with_suffix(".log.json").write_text(json.dumps(log, indent=2))
    sys.stdout.write(json.dumps(log, indent=2) + "\n")
    if "error" in log:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

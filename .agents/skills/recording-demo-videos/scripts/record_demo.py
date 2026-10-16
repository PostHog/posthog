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
import time
import base64
import shutil
import asyncio
import tempfile
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Locator, Page, async_playwright

DEFAULT_VIEWPORT = {"width": 1440, "height": 900}
FIRST_LOAD_TIMEOUT_MS = 300_000
STEP_TIMEOUT_MS = 120_000
# A wait longer than this is cut from the final video, keeping this many seconds of it.
CUT_KEEP_SECONDS = 0.6
FPS = 25
# The debug chrome of a local dev stack. It is noise in a demo.
DEFAULT_HIDE_SELECTORS = [".tricolor"]
DEFAULT_HIDE_TEXT = ["DEBUG mode"]
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
        "(() => { const C = "
        + json.dumps(config)
        + r""";
  const ensure = () => {
    if (!document.body || document.getElementById('__demo_cursor')) return;
    if (C.fontCss) { const s = document.createElement('style'); s.textContent = C.fontCss; document.head.appendChild(s); }
    const cursor = document.createElement('div'); cursor.id = '__demo_cursor';
    cursor.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;'
      + 'background:' + C.accent + '55;border:2px solid ' + C.accent + ';z-index:2147483647;pointer-events:none;'
      + 'transition:transform .08s;transform:translate(-100px,-100px)';
    document.body.appendChild(cursor);
    const cap = document.createElement('div'); cap.id = '__demo_caption';
    cap.style.cssText = 'position:fixed;left:50%;bottom:32px;transform:translateX(-50%);max-width:1080px;padding:14px 24px;'
      + 'border-radius:10px;border-left:6px solid ' + C.accent + ';background:' + C.dark + 'ee;color:' + C.cream + ';'
      + 'font:700 21px/1.35 RoundHog,-apple-system,Inter,sans-serif;z-index:2147483646;pointer-events:none;'
      + 'text-align:left;box-shadow:0 10px 30px rgba(0,0,0,.25);display:none';
    document.body.appendChild(cap);
    let x = -100, y = -100, s = 1;
    const paint = () => { cursor.style.transform = `translate(${x}px,${y}px) scale(${s})`; };
    document.addEventListener('mousemove', e => { x = e.clientX; y = e.clientY; paint(); }, true);
    document.addEventListener('mousedown', () => { s = 0.7; paint(); }, true);
    document.addEventListener('mouseup', () => { s = 1; paint(); }, true);
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
    """`${NAME}` substitution. Secret values are used for requests but shown as `$NAME`."""

    def __init__(self, values: dict[str, str], secrets: list[str]) -> None:
        self.values = values
        self.secrets = set(secrets)

    def real(self, value: Any) -> Any:
        return self._walk(value, show=False)

    def shown(self, value: Any) -> Any:
        return self._walk(value, show=True)

    def _walk(self, value: Any, show: bool) -> Any:
        if isinstance(value, str):
            return re.sub(r"\$\{(\w+)\}", lambda m: self._one(m.group(1), show), value)
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


class Recorder:
    def __init__(self, storyboard: dict[str, Any], brand: Brand, variables: Vars) -> None:
        self.sb = storyboard
        self.brand = brand
        self.vars = variables
        self.base_url = storyboard.get("base_url", "http://localhost:8010").rstrip("/")
        self.cuts: list[tuple[float, float]] = []
        self.t0 = 0.0

    def now(self) -> float:
        return time.monotonic() - self.t0

    async def waited(self, coro: Any, keep: float = CUT_KEEP_SECONDS) -> None:
        start = self.now()
        await coro
        end = self.now()
        if end - start > keep + 0.6:
            self.cuts.append((round(start + keep, 2), round(end - 0.3, 2)))

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
        await page.evaluate("t => window.__caption && window.__caption(t)", self.vars.shown(text))

    async def glide(self, page: Page, loc: Locator) -> None:
        await loc.wait_for(state="visible", timeout=STEP_TIMEOUT_MS)
        await loc.scroll_into_view_if_needed()
        box = await loc.bounding_box()
        if box:
            await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=25)
            await asyncio.sleep(0.4)

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

    async def card(self, page: Page, spec: dict[str, Any], dark: bool = False) -> None:
        html = card_html(
            self.brand,
            self.vars.shown(spec.get("heading", "")),
            self.vars.shown(spec.get("subheading", "")),
            self.brand.hog(spec.get("hog")),
            dark=dark,
        )
        await page.set_content(html)
        await asyncio.sleep(spec.get("hold", 4))

    async def http(self, page: Page, spec: dict[str, Any]) -> None:
        method = spec.get("method", "POST").upper()
        shown_url, real_url = self.vars.shown(self.url(spec["url"])), self.url(spec["url"])
        headers = spec.get("headers", {})
        body = spec.get("json")
        lines = [f"$ curl -X {method} {shown_url} \\"]
        for name, value in self.vars.shown(headers).items():
            lines.append(f'    -H "{name}: {value}" \\')
        if body is not None:
            lines.append('    -H "Content-Type: application/json" \\')
            lines.append(f"    -d '{json.dumps(self.vars.shown(body), indent=2)}'")
        command = "\n".join(lines).rstrip(" \\")
        await page.set_content(terminal_html(self.brand, self.vars.shown(spec.get("title", ""))))
        await page.evaluate(
            """async (t) => { const el = document.getElementById('cmd');
               for (let i = 0; i < t.length; i += 3) { el.textContent = t.slice(0, i + 3); await new Promise(r => setTimeout(r, 12)); } }""",
            command,
        )
        await asyncio.sleep(1)
        data = json.dumps(self.vars.real(body)).encode() if body is not None else None
        request = urllib.request.Request(real_url, data=data, method=method, headers=self.vars.real(headers))
        if body is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        try:
            text = json.dumps(json.loads(raw), indent=2)
        except ValueError:
            text = raw.decode(errors="replace")[:1500]
        await page.evaluate(
            "([t, bad]) => { const el = document.getElementById('out'); el.textContent = t; if (bad) el.className = 'bad'; }",
            [f"HTTP {status}\n{text}", status >= 400],
        )
        expected = spec.get("expect_status")
        if expected and status != expected:
            raise RuntimeError(f"{method} {shown_url} returned {status}, expected {expected}: {text[:300]}")
        await asyncio.sleep(spec.get("hold", 4))

    async def step(self, page: Page, step: dict[str, Any]) -> None:
        if "card" in step:
            await self.card(page, step["card"])
            return
        if "http" in step:
            await self.http(page, step["http"])
            return
        if "goto" in step:
            await self.waited(page.goto(self.url(step["goto"]), timeout=FIRST_LOAD_TIMEOUT_MS), keep=0.2)
        if "wait_for" in step and "goto" in step:
            await self.waited(self.locate(page, step["wait_for"]).wait_for(timeout=STEP_TIMEOUT_MS), keep=0.2)
        if "caption" in step:
            await self.caption(page, step["caption"])
        if "scroll" in step:
            await page.mouse.wheel(0, step["scroll"])
            await asyncio.sleep(0.6)
        if "hover" in step:
            await self.glide(page, self.locate(page, step["hover"]))
        if "click" in step:
            loc = self.locate(page, step["click"])
            await self.glide(page, loc)
            await loc.click()
        if "type" in step:
            spec = step["type"]
            if "target" in spec:
                loc = self.locate(page, spec["target"])
                await self.glide(page, loc)
                await loc.click()
            for key in spec.get("keys", []):
                name, _, times = key.partition(" x")
                for _ in range(int(times or 1)):
                    await page.keyboard.press(name)
            await page.keyboard.type(self.vars.real(spec.get("text", "")), delay=spec.get("delay_ms", 80))
        if "wait_for" in step and "goto" not in step:
            await self.waited(self.locate(page, step["wait_for"]).wait_for(timeout=STEP_TIMEOUT_MS))
        default_hold = max(2.5, len(step.get("caption", "").split()) * 0.32)
        await asyncio.sleep(step.get("hold", default_hold))

    async def run(self, output: Path) -> dict[str, Any]:
        viewport = self.sb.get("viewport", DEFAULT_VIEWPORT)
        video_dir = Path(tempfile.mkdtemp(prefix="demo-video-"))
        log: dict[str, Any] = {"output": str(output)}
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
                    await self.card(page, self.sb["title"])
                for index, step in enumerate(self.sb["steps"]):
                    log["step"] = index
                    await self.step(page, step)
                await self.caption(page, "")
                if "end" in self.sb:
                    await self.card(page, self.sb["end"])
                log["duration"] = round(self.now(), 2)
            except Exception as error:
                log["error"] = f"step {log.get('step')}: {error!r}"[:800]
                await page.screenshot(path=str(output.with_suffix(".error.png")))
            finally:
                raw_video = Path(await page.video.path()) if page.video else None
                await context.close()
                await browser.close()
        log["cuts"] = self.cuts
        if raw_video and "error" not in log:
            encode(raw_video, output, self.cuts, log["duration"])
            contact_sheet(output)
        elif raw_video:
            shutil.copy(raw_video, output.with_suffix(".failed.webm"))
        shutil.rmtree(video_dir, ignore_errors=True)
        return log


def encode(raw: Path, output: Path, cuts: list[tuple[float, float]], duration: float) -> None:
    keep = f"between(t,0,{duration + 0.5})"
    if cuts:
        keep += "*not(" + "+".join(f"between(t,{a},{b})" for a, b in cuts) + ")"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
            "-vf", f"fps={FPS},select='{keep}',setpts=N/{FPS}/TB",
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "22",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
        ],
        check=True,
    )  # fmt: skip


def contact_sheet(video: Path) -> None:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    every = max(float(probe.stdout.strip()) / 16, 0.5)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
            "-vf", f"fps=1/{every:.2f},scale=480:-1,tile=4x4", "-frames:v", "1",
            str(video.with_suffix(".sheet.png")),
        ],
        check=True,
    )  # fmt: skip


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is missing. Install it first (apt-get install -y ffmpeg, or brew install ffmpeg).")
    storyboard_path = Path(sys.argv[1]).resolve()
    storyboard = json.loads(storyboard_path.read_text())
    repo_root = Path(
        subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() or "."
    )
    output = (storyboard_path.parent / storyboard.get("output", "demo.mp4")).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    values = {**os.environ, **storyboard.get("vars", {})}
    recorder = Recorder(storyboard, Brand(repo_root), Vars(values, storyboard.get("secrets", [])))
    log = asyncio.run(recorder.run(output))
    output.with_suffix(".log.json").write_text(json.dumps(log, indent=2))
    sys.stdout.write(json.dumps(log, indent=2) + "\n")
    if "error" in log:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

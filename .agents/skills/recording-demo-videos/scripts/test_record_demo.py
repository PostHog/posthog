import json
import base64
import subprocess
from pathlib import Path
from typing import Any

import pytest

import record_demo


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def _duration(path: Path, stream: str) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", "stream=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return float(probe.stdout.strip())


def _storyboard(tmp_path: Path, **fields: Any) -> Path:
    path = tmp_path / "storyboard.json"
    path.write_text(json.dumps({"output": "demo.mp4", "steps": [{"goto": "/"}], **fields}))
    return path


@pytest.mark.timeout(60)
@pytest.mark.parametrize("sound_seconds", [0.5, 5.0], ids=["sound inside the video", "sound outlasts the video"])
def test_the_soundtrack_ends_with_the_video(tmp_path: Path, sound_seconds: float) -> None:
    video, sound, output = tmp_path / "raw.mp4", tmp_path / "sound.wav", tmp_path / "demo.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc=d=3:s=160x100:r=25", "-pix_fmt", "yuv420p", str(video))
    _ffmpeg("-f", "lavfi", "-i", f"sine=f=440:d={sound_seconds}", "-ac", "2", str(sound))

    record_demo.encode(video, output, [], 3.0, [(0.5, sound)], None, tmp_path)

    assert _duration(output, "a:0") == pytest.approx(_duration(output, "v:0"), abs=0.05)


@pytest.mark.parametrize(
    "system, machine, build",
    [
        ("Linux", "aarch64", "ffmpeg-release-arm64-static.tar.xz"),
        ("Linux", "arm64", "ffmpeg-release-arm64-static.tar.xz"),
        ("Linux", "x86_64", "ffmpeg-release-amd64-static.tar.xz"),
        ("Linux", "riscv64", None),
        ("Darwin", "arm64", None),
    ],
)
def test_static_ffmpeg_matches_the_machine(system: str, machine: str, build: str | None) -> None:
    url = record_demo.static_ffmpeg_url(system, machine)

    assert (url.rsplit("/", 1)[-1] if url else None) == build


STEPS = [
    {"goto": "/library", "caption": "Start here"},
    {"click": {"text": "Password reset"}},
    {"goto": "/inbox", "wait_for": {"text": "Reset"}},
    {"click": {"text": "Reset"}},
    {"click": {"role": "tab", "name": "Metrics"}},
]


@pytest.mark.parametrize(
    "steps, from_step, page, indexes, title",
    [
        (STEPS, None, None, [0, 1, 2, 3, 4], True),
        ([], None, None, [], True),
        (STEPS, 0, None, [0, 1, 2, 3, 4], False),
        (STEPS, 2, None, [2, 3, 4], False),
        (STEPS, 4, {"goto": "/inbox", "wait_for": {"text": "Reset"}}, [4], False),
    ],
    ids=["whole take", "cards only", "rehearsal from the start", "step with its own page", "step on an earlier page"],
)
def test_from_step_resumes_on_the_right_page(
    steps: list[dict], from_step: int | None, page: dict | None, indexes: list[int], title: bool
) -> None:
    resume = record_demo.resume_plan(steps, from_step)

    assert resume.page == page
    assert [index for index, _ in resume.steps] == indexes
    assert resume.title == title


def test_from_step_past_the_end_fails_before_recording() -> None:
    with pytest.raises(SystemExit, match="has 5 steps"):
        record_demo.resume_plan(STEPS, 5)


@pytest.mark.parametrize("from_step, name", [(None, "demo.mp4"), (0, "demo.from-0.mp4"), (3, "demo.from-3.mp4")])
def test_a_rehearsal_keeps_the_full_take(from_step: int | None, name: str) -> None:
    assert record_demo.take_output(Path("/videos/demo.mp4"), from_step) == Path("/videos") / name


def test_a_failing_preflight_stops_the_take_before_it_records(tmp_path: Path) -> None:
    storyboard = _storyboard(tmp_path, preflight="echo template $TEMPLATE is gone; exit 3", vars={"TEMPLATE": "7"})

    with pytest.raises(SystemExit, match="template 7 is gone"):
        record_demo.main([str(storyboard)])

    assert not (tmp_path / "demo.log.json").exists()


def test_voice_only_writes_the_narration_without_recording(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spoken: list[str] = []

    def fake_elevenlabs(url: str, body: dict[str, Any], timeout: int) -> bytes:
        spoken.append(body["text"])
        alignment = {"characters": list(body["text"])}
        return json.dumps({"audio_base64": base64.b64encode(b"narration").decode(), "alignment": alignment}).encode()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(record_demo, "elevenlabs_post", fake_elevenlabs)
    monkeypatch.setattr(record_demo, "VOICE_CACHE", tmp_path / "cache")
    monkeypatch.setattr(record_demo, "async_playwright", None)
    storyboard = _storyboard(
        tmp_path,
        voiceover={},
        title={"heading": "Transactional emails"},
        steps=[{"goto": "/", "caption": "Start from a template"}],
    )

    record_demo.main([str(storyboard), "--voice-only"])

    assert spoken == ["Transactional emails.\n\nStart from a template"]
    assert (tmp_path / "demo.voice.mp3").read_bytes() == b"narration"

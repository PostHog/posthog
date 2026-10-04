import stat
import shutil
import zipfile
from pathlib import Path
from typing import BinaryIO

import pytest

from ci_backend_master_artifacts import extract_artifact, validate_artifact_name


def write_archive(
    tmp_path: Path, members: list[tuple[str | zipfile.ZipInfo, str]], *, compression: int = zipfile.ZIP_DEFLATED
) -> Path:
    path = tmp_path / "artifact.zip"
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return path


def test_relay_preserves_artifact_names_and_nested_contents(tmp_path: Path) -> None:
    artifact_name = "test-timings-core-shard1-attempt2"
    archive = write_archive(
        tmp_path, [("reports/", ""), ("reports/junit.xml", "<testsuites/>"), ("timings.json", "{}")]
    )
    destination = tmp_path / "relay" / artifact_name
    extract_artifact(archive, destination)
    assert destination.name == artifact_name
    assert (destination / "reports/junit.xml").read_text() == "<testsuites/>"
    assert (destination / "timings.json").read_text() == "{}"


@pytest.mark.parametrize("name", ["../schema", "/schema", "schema/dump", "schema\\dump", "..", "", "name\ncommand"])
def test_untrusted_artifact_name_cannot_select_the_output_path(name: str) -> None:
    with pytest.raises(ValueError):
        validate_artifact_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "safe/../../outside",
        "/outside",
        "C:/outside",
        "safe\\outside",
        "./outside",
        "a//b",
        "name\ncommand",
    ],
)
def test_every_member_is_validated_before_any_file_is_written(tmp_path: Path, name: str) -> None:
    archive = write_archive(tmp_path, [("junit.xml", "<testsuites/>"), (name, "untrusted")])
    destination = tmp_path / "relay"
    with pytest.raises(ValueError, match="unsafe member"):
        extract_artifact(archive, destination)
    assert not destination.exists()
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize("kind", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR])
def test_archive_cannot_create_links_or_special_files(tmp_path: Path, kind: int) -> None:
    member = zipfile.ZipInfo("reports/link")
    member.create_system = 3
    member.external_attr = (kind | 0o777) << 16
    archive = write_archive(tmp_path, [(member, "../../outside")])
    destination = tmp_path / "relay"
    with pytest.raises(ValueError, match="link or special"):
        extract_artifact(archive, destination)
    assert not destination.exists()


@pytest.mark.parametrize("members", [[("a", "x"), ("a/child", "y")], [("a/b", "x"), ("a", "y")]])
def test_file_directory_conflicts_cannot_partially_extract(tmp_path: Path, members: list[tuple[str, str]]) -> None:
    archive = write_archive(tmp_path, [(name, content) for name, content in members])
    destination = tmp_path / "relay"
    with pytest.raises(ValueError, match="file as a directory"):
        extract_artifact(archive, destination)
    assert not destination.exists()


def test_duplicate_archive_paths_cannot_overwrite_a_report(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        archive = write_archive(tmp_path, [("junit.xml", "first"), ("junit.xml", "second")])
    with pytest.raises(ValueError, match="duplicate"):
        extract_artifact(archive, tmp_path / "relay")


@pytest.mark.parametrize("max_bytes,max_members", [(1, 10), (10, 1)])
def test_zip_bombs_and_excessive_member_counts_fail_before_extraction(
    tmp_path: Path, max_bytes: int, max_members: int
) -> None:
    archive = write_archive(tmp_path, [("one", "aa"), ("two", "bb")])
    destination = tmp_path / "relay"
    with pytest.raises(ValueError, match="extraction limit"):
        extract_artifact(archive, destination, max_bytes=max_bytes, max_members=max_members)
    assert not destination.exists()


def test_extraction_cannot_replace_an_existing_artifact(tmp_path: Path) -> None:
    archive = write_archive(tmp_path, [("junit.xml", "replacement")])
    destination = tmp_path / "relay"
    destination.mkdir()
    original = destination / "junit.xml"
    original.write_text("original")
    with pytest.raises(FileExistsError):
        extract_artifact(archive, destination)
    assert original.read_text() == "original"


@pytest.mark.parametrize("interrupted", [False, True])
def test_failed_extraction_does_not_leave_a_partial_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool
) -> None:
    archive = write_archive(tmp_path, [("junit.xml", "<testsuites/>")], compression=zipfile.ZIP_STORED)
    expected_error: type[BaseException] = zipfile.BadZipFile
    if interrupted:

        def interrupt(source: BinaryIO, output: BinaryIO, *, length: int) -> None:
            output.write(b"partial")
            raise KeyboardInterrupt

        monkeypatch.setattr(shutil, "copyfileobj", interrupt)
        expected_error = KeyboardInterrupt
    else:
        raw = bytearray(archive.read_bytes())
        with zipfile.ZipFile(archive) as metadata:
            member = metadata.getinfo("junit.xml")
            content_start = member.header_offset + 30 + len(member.filename.encode()) + len(member.extra)
        raw[content_start] ^= 0xFF
        archive.write_bytes(raw)
    destination = tmp_path / "relay"
    with pytest.raises(expected_error):
        extract_artifact(archive, destination)
    assert not destination.exists()

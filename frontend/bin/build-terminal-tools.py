import io
import sys
import gzip
import json
import hashlib
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "public" / "terminal"
PREFIX = "opt/posthog-tools"


def download(url: str, algorithm: str, expected: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    if hashlib.new(algorithm, data).hexdigest() != expected:
        raise ValueError(f"Checksum mismatch: {url}")
    return data


def normalized(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = info.mtime = 0
    info.uname = info.gname = ""
    return info


def build() -> None:
    manifest = json.loads((ASSETS / "tools-manifest.json").read_text())
    with tempfile.TemporaryDirectory(prefix="posthog-terminal-tools-") as temporary:
        root = Path(temporary)
        tools = root / PREFIX
        tools.mkdir(parents=True)
        for package in manifest["packages"]:
            data = download(f"{manifest['repository']}/{package['file']}", "sha256", package["sha256"])
            # APK signatures, metadata, and payload are concatenated tar streams.
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz", ignore_zeros=True) as archive:
                members = [member for member in archive if member.name.startswith(("etc/", "lib/", "usr/"))]
                archive.extractall(tools, members=members, filter="data")

        licenses = tools / "licenses"
        licenses.mkdir()
        for source in manifest["sources"]:
            data = download(source["url"], "sha512", source["sha512"])
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                license_file = archive.extractfile(source["license_file"])
                if license_file is None:
                    raise ValueError(f"Missing license: {source['name']}")
                (licenses / f"{source['name']}.txt").write_bytes(license_file.read())
        (licenses / "tools-manifest.json").write_bytes((ASSETS / "tools-manifest.json").read_bytes())
        (tools / "etc/nanorc").write_text(f'include "/{PREFIX}/usr/share/nano/*.nanorc"\n')

        wrappers = root / "usr/bin"
        wrappers.mkdir(parents=True)
        for command in ("nano", "tree", "ncdu"):
            arguments = f"--rcfile=/{PREFIX}/etc/nanorc " if command == "nano" else ""
            wrapper = wrappers / command
            # Isolate musl and ncurses from the guest's existing uClibc programs.
            wrapper.write_text(
                "#!/bin/sh\n"
                f"export TERMINFO=/{PREFIX}/etc/terminfo LANG=C.UTF-8\n"
                'export TZ="$(cat /etc/TZ)"\n'
                f"exec /{PREFIX}/lib/ld-musl-i386.so.1 "
                f"--library-path /{PREFIX}/lib:/{PREFIX}/usr/lib "
                f'/{PREFIX}/usr/bin/{command} {arguments}"$@"\n'
            )
            wrapper.chmod(0o755)

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for path in sorted(root.rglob("*")):
                archive.add(path, arcname=path.relative_to(root), recursive=False, filter=normalized)
        # A fixed gzip header keeps the vendored archive reproducible.
        with io.BytesIO() as compressed:
            with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", mtime=0) as output:
                output.write(buffer.getvalue())
            bundle = compressed.getvalue()
        (ASSETS / "tools-linux-i386.tar.gz.bin").write_bytes(bundle)
        sys.stdout.write(
            f"tools-linux-i386.tar.gz.bin: {len(bundle)} bytes, SHA-256 {hashlib.sha256(bundle).hexdigest()}\n"
        )


if __name__ == "__main__":
    build()

# Installs hog, the PostHog command line, on Windows.
#
#   irm https://releases.posthog.com/hog/install.ps1 | iex
#
# To pass options, download the script first, or set the environment variables:
#   -Version <version>   HOG_VERSION       Install this version instead of the latest one
#   -InstallDir <folder> HOG_INSTALL_DIR   Where to put hog.exe. Defaults to ~\.local\bin
#
# Everything runs from Install-Hog, called on the last line, so a download cut short runs nothing.

param(
    [string]$Version = $env:HOG_VERSION,
    [string]$InstallDir = $env:HOG_INSTALL_DIR
)

function Install-Hog {
    param([string]$Version, [string]$InstallDir)

    # PowerShell 6 and later run on macOS and Linux too, where the sh script installs the right build.
    # A return rather than exit, because `irm | iex` runs in the caller's session and exit would close it.
    if ($PSVersionTable.PSVersion.Major -ge 6 -and -not $IsWindows) {
        Write-Host 'This script is for Windows. On macOS and Linux, install hog with: curl -fsSL https://releases.posthog.com/hog/install.sh | sh'
        return
    }

    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $releases = if ($env:HOG_RELEASES_URL) { $env:HOG_RELEASES_URL } else { 'https://releases.posthog.com/hog' }
    $mirror = if ($env:HOG_MIRROR_URL) { $env:HOG_MIRROR_URL } else { 'https://github.com/PostHog/posthog/releases/download' }

    if (-not $InstallDir) { $InstallDir = Join-Path $HOME '.local\bin' }

    $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    $target = switch ($arch) {
        'X64' { 'windows-x64' }
        'Arm64' { 'windows-arm64' }
        default { throw "There is no hog build for $arch processors." }
    }

    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("hog-install-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        if ($Version) {
            $Version = $Version.TrimStart('v')
        } else {
            try {
                $manifest = Invoke-RestMethod -Uri "$releases/stable/manifest.json"
            } catch {
                throw "Couldn't find the latest hog release at $releases/stable/manifest.json."
            }
            $Version = $manifest.version
            if (-not $Version) { throw 'The release manifest names no version.' }
        }

        $archive = "hog-$target.zip"
        Write-Host "Installing hog $Version for $target."

        # The release bucket first and the GitHub release second, so one origin being down doesn't stop an install.
        foreach ($file in @('SHA256SUMS', $archive)) {
            $destination = Join-Path $tmp $file
            try {
                Invoke-WebRequest -Uri "$releases/v$Version/$file" -OutFile $destination -UseBasicParsing
            } catch {
                Invoke-WebRequest -Uri "$mirror/hog/v$Version/$file" -OutFile $destination -UseBasicParsing
            }
        }

        $line = Get-Content (Join-Path $tmp 'SHA256SUMS') | Where-Object { ($_ -split '\s+')[1] -eq $archive } | Select-Object -First 1
        if (-not $line) { throw "SHA256SUMS for hog $Version has no entry for $archive." }
        $expected = ($line -split '\s+')[0].ToLowerInvariant()
        $actual = (Get-FileHash -Algorithm SHA256 (Join-Path $tmp $archive)).Hash.ToLowerInvariant()
        if ($expected -ne $actual) { throw "The checksum of $archive doesn't match SHA256SUMS. Nothing was installed." }

        Expand-Archive -Path (Join-Path $tmp $archive) -DestinationPath (Join-Path $tmp 'unpacked')
        $binary = Join-Path $tmp 'unpacked\hog.exe'
        if (-not (Test-Path $binary)) { throw "$archive has no hog.exe." }

        # Windows can't overwrite a running exe, but it can rename one. The old copy goes aside first,
        # so a hog that is running keeps working and the new one takes its place.
        New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
        $exe = Join-Path $InstallDir 'hog.exe'
        $old = Join-Path $InstallDir 'hog.old.exe'
        if (Test-Path $old) { Remove-Item -Force $old -ErrorAction SilentlyContinue }
        if (Test-Path $exe) { Move-Item -Force $exe $old }
        Move-Item -Force $binary $exe
        if (Test-Path $old) { Remove-Item -Force $old -ErrorAction SilentlyContinue }

        $installed = & $exe --version
        if ($LASTEXITCODE -ne 0) { throw "The installed hog at $exe doesn't run." }

        # Best effort: hog works without the receipt, which tells a later upgrade that this script owns the binary.
        try {
            $configDir = Join-Path $env:LOCALAPPDATA 'hog'
            New-Item -ItemType Directory -Force -Path $configDir | Out-Null
            @{ method = 'script'; install_dir = $InstallDir; version = $Version; target = $target } |
                ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $configDir 'install.json')
        } catch {}

        Write-Host "Installed hog $installed to $exe."

        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        $onPath = ($userPath -split ';') + ($env:Path -split ';') | Where-Object { $_.TrimEnd('\') -ieq $InstallDir.TrimEnd('\') }
        if (-not $onPath) {
            Write-Host ''
            Write-Host "$InstallDir isn't on your PATH yet. Add it, then open a new terminal:"
            Write-Host "  [Environment]::SetEnvironmentVariable('Path', `"$InstallDir;`" + [Environment]::GetEnvironmentVariable('Path', 'User'), 'User')"
        }
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
}

Install-Hog -Version $Version -InstallDir $InstallDir

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

    # Color for a person at a terminal, unless NO_COLOR asks for none (https://no-color.org).
    $color = -not $env:NO_COLOR -and -not [Console]::IsOutputRedirected
    function Write-Styled([string]$Text, [ConsoleColor]$Foreground, [switch]$NoNewline) {
        if ($color) {
            Write-Host $Text -ForegroundColor $Foreground -NoNewline:$NoNewline
        } else {
            Write-Host $Text -NoNewline:$NoNewline
        }
    }

    # curl.exe ships with Windows 10 1803 and later. It draws a progress bar, and it gives up on a stalled
    # transfer, so a stalled bucket falls back to the mirror. Invoke-WebRequest covers older systems:
    # -TimeoutSec bounds the whole download in PowerShell 7, and Windows PowerShell gives up on a stalled
    # read after HttpWebRequest's ReadWriteTimeout, 5 minutes by default.
    # A $Mode of 'quiet' hides curl's error, for a download that has a fallback, and 'progress' draws the bar.
    $curl = Get-Command curl.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    function Get-HogFile([string]$Uri, [string]$OutFile, [string]$Mode) {
        if ($curl) {
            $proto = if ($Uri.StartsWith('https://')) { '=https' } else { '=https,http,file' }
            $report = switch ($Mode) {
                'quiet' { '-s' }
                'progress' { if ([Console]::IsErrorRedirected) { '-sS' } else { '-#' } }
                default { '-sS' }
            }
            & $curl.Source --proto $proto --tlsv1.2 -fL $report --retry 3 --connect-timeout 10 `
                --speed-limit 1024 --speed-time 30 -o $OutFile $Uri
            if ($LASTEXITCODE -ne 0) { throw "Couldn't download $Uri." }
        } else {
            Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing -TimeoutSec 600
        }
    }

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
            $manifestFile = Join-Path $tmp 'manifest.json'
            try {
                Get-HogFile "$releases/latest/manifest.json" $manifestFile 'quiet'
                $manifest = Get-Content -Raw $manifestFile | ConvertFrom-Json
            } catch {
                throw "Couldn't find the latest hog release at $releases/latest/manifest.json."
            }
            $Version = $manifest.version
            if (-not $Version) { throw 'The release manifest names no version.' }
        }

        $archive = "hog-$target.zip"

        # The hedgehog of the hobby installer, bin/hobby-installer/ui/hedgehog.go.
        $art = @('  \-|-/', ' / ^.^ \', ' \  w  /', "  '---'")
        $text = @('', '   hog, the PostHog command line', "   Installing hog $Version for $target.", '')
        for ($i = 0; $i -lt $art.Count; $i++) {
            Write-Styled $art[$i] Yellow -NoNewline
            Write-Host $text[$i]
        }
        Write-Host ''

        # The release bucket first and the GitHub release second, so one origin being down doesn't stop an
        # install. After one miss, the rest of the files come from the mirror.
        $useMirror = $false
        foreach ($file in @('SHA256SUMS', $archive)) {
            $destination = Join-Path $tmp $file
            $mode = if ($file -eq $archive) { 'progress' } else { '' }
            $bucketMode = if ($mode) { $mode } else { 'quiet' }
            if (-not $useMirror) {
                try {
                    Get-HogFile "$releases/v$Version/$file" $destination $bucketMode
                    continue
                } catch {
                    $useMirror = $true
                    Write-Styled "Couldn't download $file from $releases, so the rest comes from the GitHub mirror." DarkGray
                }
            }
            try {
                Get-HogFile "$mirror/hog/v$Version/$file" $destination $mode
            } catch {
                throw "Couldn't download $file for hog $Version."
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

        # Run before the swap, so a build that can't run here never replaces a working hog. A build Windows
        # can't start throws instead of setting an exit code.
        $runs = $false
        try {
            $installed = & $binary --version
            $runs = ($LASTEXITCODE -eq 0) -and $installed
        } catch {}
        if (-not $runs) { throw "hog $Version doesn't run on this machine, so the install changed nothing." }

        # Windows can't overwrite a running exe, but it can rename one. The old copy goes aside, and comes
        # back if the new one can't take its place.
        New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
        $exe = Join-Path $InstallDir 'hog.exe'
        $old = Join-Path $InstallDir 'hog.old.exe'
        if (Test-Path $old) { Remove-Item -Force $old -ErrorAction SilentlyContinue }
        if (Test-Path $exe) { Move-Item -Force $exe $old }
        try {
            Move-Item -Force $binary $exe
        } catch {
            if (Test-Path $old) { Move-Item -Force $old $exe }
            throw
        }
        if (Test-Path $old) { Remove-Item -Force $old -ErrorAction SilentlyContinue }

        # Best effort: hog works without the receipt, which tells a later upgrade that this script owns the binary.
        try {
            $configDir = Join-Path $env:LOCALAPPDATA 'hog'
            New-Item -ItemType Directory -Force -Path $configDir | Out-Null
            @{ method = 'script'; install_dir = $InstallDir; version = $Version; target = $target } |
                ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $configDir 'install.json')
        } catch {}

        Write-Styled "Installed hog $installed" Green -NoNewline
        Write-Host " to $exe."

        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        $onPath = ($userPath -split ';') + ($env:Path -split ';') | Where-Object { $_.TrimEnd('\') -ieq $InstallDir.TrimEnd('\') }
        if (-not $onPath) {
            Write-Host ''
            Write-Host "$InstallDir isn't on your PATH yet. Add it, then open a new terminal:"
            Write-Host "  [Environment]::SetEnvironmentVariable('Path', `"$InstallDir;`" + [Environment]::GetEnvironmentVariable('Path', 'User'), 'User')"
        }

        Write-Host ''
        Write-Host 'Next, run ' -NoNewline
        Write-Styled 'hog setup' White -NoNewline
        Write-Host " in your project's folder to add PostHog to it."
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
}

Install-Hog -Version $Version -InstallDir $InstallDir

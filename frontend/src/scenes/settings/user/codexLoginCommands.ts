export type CodexLoginPlatform = 'macos' | 'linux' | 'windows'

export const CODEX_LOGIN_PLATFORM_OPTIONS: { value: CodexLoginPlatform; label: string }[] = [
    { value: 'macos', label: 'macOS' },
    { value: 'linux', label: 'Linux' },
    { value: 'windows', label: 'Windows' },
]

const CODEX_LOGIN = 'codex login --device-auth -c cli_auth_credentials_store=file'
const COPIED_MESSAGE = 'Copied. Paste it in PostHog.'

const LINUX_COPY =
    'if [ -n "$WAYLAND_DISPLAY" ] && command -v wl-copy >/dev/null; then wl-copy < "$d/auth.json"; ' +
    'elif command -v xclip >/dev/null; then xclip -selection clipboard < "$d/auth.json"; ' +
    'else xsel --clipboard --input < "$d/auth.json"; fi'

function posixLoginCommand(copyToClipboard: string): string {
    return (
        `sh -c 'd=$(mktemp -d) && trap "rm -rf \\"$d\\"" EXIT INT TERM HUP && ` +
        `CODEX_HOME="$d" ${CODEX_LOGIN} && ${copyToClipboard} && echo "${COPIED_MESSAGE}"'`
    )
}

const WINDOWS_LOGIN_COMMAND =
    '$d = Join-Path $env:TEMP ([guid]::NewGuid()); $h = $env:CODEX_HOME; ' +
    'New-Item -ItemType Directory -Path $d | Out-Null; ' +
    `try { $env:CODEX_HOME = $d; ${CODEX_LOGIN}; ` +
    `if ($LASTEXITCODE -eq 0) { Get-Content -Raw (Join-Path $d 'auth.json') | Set-Clipboard; '${COPIED_MESSAGE}' } } ` +
    'finally { $env:CODEX_HOME = $h; Remove-Item -Recurse -Force $d }'

export function codexLoginCommand(platform: CodexLoginPlatform): string {
    switch (platform) {
        case 'macos':
            return posixLoginCommand('pbcopy < "$d/auth.json"')
        case 'linux':
            return posixLoginCommand(LINUX_COPY)
        case 'windows':
            return WINDOWS_LOGIN_COMMAND
    }
}

export function detectCodexLoginPlatform(platform: string, userAgent: string): CodexLoginPlatform {
    const source = `${platform} ${userAgent}`.toLowerCase()
    if (source.includes('mac')) {
        return 'macos'
    }
    if (source.includes('win')) {
        return 'windows'
    }
    if (source.includes('linux') || source.includes('x11') || source.includes('cros')) {
        return 'linux'
    }
    return 'macos'
}

export function browserCodexLoginPlatform(): CodexLoginPlatform {
    const nav = navigator as Navigator & { userAgentData?: { platform?: string } }
    return detectCodexLoginPlatform(nav.userAgentData?.platform || nav.platform || '', nav.userAgent)
}

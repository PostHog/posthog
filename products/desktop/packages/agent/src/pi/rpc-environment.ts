const SAFE_ENVIRONMENT_KEYS = [
  "APPDATA",
  "COLORTERM",
  "ComSpec",
  "FORCE_COLOR",
  "HOME",
  "LANG",
  "LC_ALL",
  "LOCALAPPDATA",
  "LOGNAME",
  "NO_COLOR",
  "PATH",
  "PATHEXT",
  "SHELL",
  "SystemRoot",
  "TEMP",
  "TERM",
  "TMP",
  "TMPDIR",
  "USER",
  "USERPROFILE",
  "WINDIR",
  "XDG_CACHE_HOME",
  "XDG_CONFIG_HOME",
  "XDG_DATA_HOME",
  "XDG_RUNTIME_DIR",
  "XDG_STATE_HOME",
] as const;

export function safePiEnvironment(
  source: NodeJS.ProcessEnv,
): Record<string, string> {
  const environment: Record<string, string> = {};
  for (const key of SAFE_ENVIRONMENT_KEYS) {
    const value = source[key];
    if (value !== undefined) {
      environment[key] = value;
    }
  }
  return environment;
}

export function sanitizePiHostEnvironment(): void {
  const environment = safePiEnvironment(process.env);
  for (const key of Object.keys(process.env)) {
    delete process.env[key];
  }
  Object.assign(process.env, environment);
}

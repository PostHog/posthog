import { execFileSync } from 'node:child_process'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { readFileSync, writeFileSync, mkdirSync, unlinkSync } from 'node:fs'

const SERVICE_NAME = 'posthog-cli-livestream'
const ACCOUNT_NAME = 'credentials'

// Fallback file path for non-macOS systems
const getFilePath = () => join(homedir(), '.posthog', 'livestream.json')

const isMacOS = process.platform === 'darwin'

// macOS Keychain functions using `security` CLI
const keychainGet = (): string | null => {
  try {
    const result = execFileSync(
      'security',
      ['find-generic-password', '-s', SERVICE_NAME, '-a', ACCOUNT_NAME, '-w'],
      { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'ignore'] }
    )
    return result.trim()
  } catch {
    return null
  }
}

const keychainSet = (value: string): void => {
  try {
    execFileSync('security', ['delete-generic-password', '-s', SERVICE_NAME, '-a', ACCOUNT_NAME],
      { stdio: 'ignore' })
  } catch { /* ignore */ }

  execFileSync('security',
    ['add-generic-password', '-s', SERVICE_NAME, '-a', ACCOUNT_NAME, '-w', value],
    { encoding: 'utf-8' })
}

const keychainDelete = (): void => {
  try {
    execFileSync('security', ['delete-generic-password', '-s', SERVICE_NAME, '-a', ACCOUNT_NAME],
      { stdio: 'ignore' })
  } catch { /* ignore */ }
}

// File-based fallback for non-macOS
const fileGet = (): string | null => {
  try {
    return readFileSync(getFilePath(), 'utf-8')
  } catch {
    return null
  }
}

const fileSet = (value: string): void => {
  const filePath = getFilePath()
  mkdirSync(join(homedir(), '.posthog'), { recursive: true })
  writeFileSync(filePath, value, { mode: 0o600 }) // Restrict permissions
}

const fileDelete = (): void => {
  try {
    unlinkSync(getFilePath())
  } catch {
    // Ignore - file might not exist
  }
}

// Public API
export const secureStorage = {
  get: (): string | null => {
    if (isMacOS) {
      return keychainGet()
    }
    return fileGet()
  },

  set: (value: string): void => {
    if (isMacOS) {
      keychainSet(value)
    } else {
      fileSet(value)
    }
  },

  delete: (): void => {
    if (isMacOS) {
      keychainDelete()
    } else {
      fileDelete()
    }
  },

  isSecure: isMacOS,
}

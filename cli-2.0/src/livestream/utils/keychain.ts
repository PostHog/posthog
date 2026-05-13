import { execSync } from 'node:child_process'
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
    const result = execSync(
      `security find-generic-password -s "${SERVICE_NAME}" -a "${ACCOUNT_NAME}" -w 2>/dev/null`,
      { encoding: 'utf-8' }
    )
    return result.trim()
  } catch {
    return null
  }
}

const keychainSet = (value: string): void => {
  // Delete existing entry first (ignore errors if it doesn't exist)
  try {
    execSync(`security delete-generic-password -s "${SERVICE_NAME}" -a "${ACCOUNT_NAME}" 2>/dev/null`)
  } catch {
    // Ignore - entry might not exist
  }

  // Add new entry
  execSync(
    `security add-generic-password -s "${SERVICE_NAME}" -a "${ACCOUNT_NAME}" -w "${value.replace(/"/g, '\\"')}"`,
    { encoding: 'utf-8' }
  )
}

const keychainDelete = (): void => {
  try {
    execSync(`security delete-generic-password -s "${SERVICE_NAME}" -a "${ACCOUNT_NAME}" 2>/dev/null`)
  } catch {
    // Ignore - entry might not exist
  }
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

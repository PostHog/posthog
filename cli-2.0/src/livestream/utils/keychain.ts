import { Entry } from '@napi-rs/keyring'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { readFileSync, writeFileSync, mkdirSync, unlinkSync } from 'node:fs'

const SERVICE_NAME = 'posthog-cli-livestream'
const ACCOUNT_NAME = 'credentials'

// Fallback file path when keyring is unavailable
const getFilePath = () => join(homedir(), '.posthog', 'livestream.json')

// Probe keyring availability
let useKeyring = false
try {
  new Entry(SERVICE_NAME, '__probe__').getPassword()
  useKeyring = true
} catch {
  // Keyring unavailable (e.g., no libsecret on Linux, or headless environment)
}

// Keyring-based storage using @napi-rs/keyring
const keyringGet = (): string | null => {
  try {
    const entry = new Entry(SERVICE_NAME, ACCOUNT_NAME)
    const value = entry.getPassword()
    return value ?? null
  } catch {
    return null
  }
}

const keyringSet = (value: string): void => {
  const entry = new Entry(SERVICE_NAME, ACCOUNT_NAME)
  entry.setPassword(value)
}

const keyringDelete = (): void => {
  try {
    const entry = new Entry(SERVICE_NAME, ACCOUNT_NAME)
    entry.deletePassword()
  } catch {
    // Already absent or backend unavailable
  }
}

// File-based fallback
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
  writeFileSync(filePath, value, { mode: 0o600 })
}

const fileDelete = (): void => {
  try {
    unlinkSync(getFilePath())
  } catch {
    // File might not exist
  }
}

// Public API
export const secureStorage = {
  get: (): string | null => {
    if (useKeyring) {
      return keyringGet()
    }
    return fileGet()
  },

  set: (value: string): void => {
    if (useKeyring) {
      keyringSet(value)
    } else {
      fileSet(value)
    }
  },

  delete: (): void => {
    if (useKeyring) {
      keyringDelete()
    } else {
      fileDelete()
    }
  },

  isSecure: useKeyring,
}

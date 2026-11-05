// @ts-nocheck
// Test fixture for the hog-typed-boundaries rules.
import { parseJson } from '@/core/json'
import { parseHost } from '@/posthog/host'

// ruleid: hog-json-parse-outside-json-helper
const settings = JSON.parse(text)

// ok: hog-json-parse-outside-json-helper
const checked = parseJson(text, Settings, { code: 'invalid_settings' })

// ruleid: hog-host-cast-outside-host-module
const host = raw as Host

// ruleid: hog-host-cast-outside-host-module
const key = origin as HostKey

// ok: hog-host-cast-outside-host-module
const parsed = parseHost(raw)

// A cast through `unknown` is still a cast to the brand.
// ruleid: hog-id-cast-outside-ids-module
const projectId = (value as unknown) as ProjectId

// ruleid: hog-id-cast-outside-ids-module
const organizationId = value as OrganizationId

// ruleid: hog-token-cast-outside-tokens-module
const apiKey = value as PersonalApiKey

// ruleid: hog-token-cast-outside-tokens-module
const accessToken = value as OAuthAccessToken

// A type that only contains a brand name is not a brand.
// ok: hog-token-cast-outside-tokens-module
const kinds = value as PersonalApiKeyKinds

// ok: hog-host-cast-outside-host-module
const text2 = value as string

// @ts-nocheck
// Test fixture for the hog-typed-boundaries rules.
import { parseJson } from '@/core/json'
import { parseHost } from '@/posthog/host'

// ruleid: hog-json-parse-outside-json-helper
const settings = JSON.parse(text)

// ruleid: hog-json-parse-outside-json-helper
const rows = lines.map(JSON.parse)

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

// A union or a list of a brand is a cast to the brand too.
// ruleid: hog-id-cast-outside-ids-module
const maybeProjectId = value as ProjectId | undefined

// ruleid: hog-host-cast-outside-host-module
const hosts = values as Host[]

// ruleid: hog-host-cast-outside-host-module
const hostList = values as Array<Host>

// ruleid: hog-id-cast-outside-ids-module
const optionalProjectId = value as undefined | ProjectId

// ruleid: hog-token-cast-outside-tokens-module
const keys = value as Record<string, PersonalApiKey>

// ruleid: hog-token-cast-outside-tokens-module
const apiKey = value as PersonalApiKey

// ruleid: hog-token-cast-outside-tokens-module
const accessToken = value as OAuthAccessToken

// A type that only contains a brand name is not a brand.
// ok: hog-token-cast-outside-tokens-module
const kinds = value as PersonalApiKeyKinds

// ok: hog-host-cast-outside-host-module
const schema = value as typeof HostSchema

// ok: hog-host-cast-outside-host-module
const text2 = value as string

// A comment that says to treat a value as Host is not a cast.
// ok: hog-host-cast-outside-host-module
const text3 = value

// ok: hog-host-cast-outside-host-module
const prose = 'treat the value as Host'

/* ok: hog-host-cast-outside-host-module */ /* treat the value as Host */
const afterBlock = value

// ok: hog-host-cast-outside-host-module
import {
    thing as Host,
} from 'elsewhere'

// ruleid: hog-host-cast-outside-host-module
const afterCall = load('x') as Host

// A URL in a string is not a comment.
// ruleid: hog-host-cast-outside-host-module
const afterUrl = 'https://example.com/?q=1' as Host

import fs from 'fs'
import path from 'path'

import { INGESTION_WARNING_TYPES } from '~/ingestion/common/ingestion-warning-types'

const SKILL_PATH = path.resolve(
    __dirname,
    '../../../..',
    'products/ingestion/skills/resolving-ingestion-warnings/SKILL.md'
)

describe('ingestion warning registry', () => {
    it('every registered type is routed by the resolving-ingestion-warnings skill', () => {
        // The skill is how an agent turns a fired `ingestion_warning` health issue into a
        // diagnosis, and the health check sends it there by name. A type registered here but
        // absent from the routing table is a dead end at exactly that hand-off, which nothing
        // else catches: the type still emits, still raises a health issue, and still resolves
        // to no guidance.
        const skill = fs.readFileSync(SKILL_PATH, 'utf8')
        const unrouted = Object.keys(INGESTION_WARNING_TYPES).filter((type) => !skill.includes(`\`${type}\``))
        expect(unrouted).toEqual([])
    })
})

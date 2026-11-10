import { z } from 'zod'

import { eventEmail } from '../generator/traffic'
import { atLeastOnce } from '../judge/invariants'

export type Definition = { name: string; params: z.ZodType }

export type TrafficDefinition = Definition & { profile: z.ZodType }

export type Definitions = {
    valves: Definition[]
    traffic: TrafficDefinition[]
    invariants: Definition[]
    measurements: Definition[]
}

export const DEFINITIONS: Definitions = {
    valves: [],
    traffic: [eventEmail],
    invariants: [atLeastOnce],
    measurements: [],
}

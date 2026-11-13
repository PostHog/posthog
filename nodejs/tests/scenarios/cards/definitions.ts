import { z } from 'zod'

import { TRAFFIC } from '../generator/traffic'
import { INVARIANTS } from '../judge/invariants'
import { MEASUREMENTS } from '../judge/measurements'

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
    traffic: TRAFFIC,
    invariants: INVARIANTS,
    measurements: MEASUREMENTS,
}

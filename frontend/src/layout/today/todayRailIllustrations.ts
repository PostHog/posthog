import { ComponentType } from 'react'

import * as chartPng from '@posthog/brand/hoggies/png/chart'
import * as constructionPng from '@posthog/brand/hoggies/png/construction-1'
import * as handClaspPng from '@posthog/brand/hoggies/png/hand-clasp'
import * as lifeguardPng from '@posthog/brand/hoggies/png/lifeguard'
import * as puzzlePng from '@posthog/brand/hoggies/png/puzzle'
import * as readingPng from '@posthog/brand/hoggies/png/reading'
import * as robotPng from '@posthog/brand/hoggies/png/robot'
import * as rocketPng from '@posthog/brand/hoggies/png/rocket'

import { HoggiePngProps, pngHoggie } from 'lib/brand/hoggies'

import type { TodayRailPane } from './todayShellLogic'

/** The hoggie on top of each rail item's hover card. Only the lazy card imports this, so the rail stays light. */
export const TODAY_RAIL_ILLUSTRATIONS: Record<TodayRailPane, ComponentType<HoggiePngProps>> = {
    home: pngHoggie(readingPng),
    spaces: pngHoggie(robotPng),
    analytics: pngHoggie(chartPng),
    monitor: pngHoggie(lifeguardPng),
    people: pngHoggie(handClaspPng),
    release: pngHoggie(rocketPng),
    products: pngHoggie(puzzlePng),
    settings: pngHoggie(constructionPng),
}

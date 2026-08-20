import * as einsteinPng from '@posthog/brand/hoggies/png/einstein'
import { IconFlask } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { autoresearchLogic } from '../autoresearchLogic'
import { AutoresearchPredictionPreview } from './AutoresearchPredictionPreview'

const HedgehogEinstein = pngHoggie(einsteinPng)

export const autoresearchEmptyState: SceneProductEmptyState = {
    statusLogic: autoresearchLogic,
    // The whole product is behind this flag; the scene's own gate handles the flag-off case.
    featureFlag: FEATURE_FLAGS.AUTORESEARCH,
    config: {
        productKey: ProductKey.AUTORESEARCH,
        productName: 'Autoresearch',
        icon: <IconFlask />,
        accentColor: 'var(--color-product-autoresearch-light)',
        accentColorDark: 'var(--color-product-autoresearch-dark)',
        hedgehog: HedgehogEinstein,
        text: {
            'needs-setup': {
                headline: 'Predict what your users will do next',
                lead: 'Pick a target event, a population, and a horizon. An agent trains and compares models until it finds the best one, then scores your users on a schedule and writes each prediction back to PostHog.',
            },
        },
        primaryAction: { label: 'New model', to: urls.autoresearchNew() },
        previewLabel: 'Predictions, once trained',
        Preview: AutoresearchPredictionPreview,
    },
}

import * as partyPng from '@posthog/brand/hoggies/png/party'
import { IconPeople } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { CohortsPreview } from './CohortsPreview'
import { cohortsSetupLogic } from './cohortsSetupLogic'

const HedgehogParty = pngHoggie(partyPng)

export const cohortsEmptyState: SceneProductEmptyState = {
    statusLogic: cohortsSetupLogic,
    config: {
        productKey: ProductKey.COHORTS,
        productName: 'Cohorts',
        icon: <IconPeople />,
        accentColor: 'var(--color-product-cohorts-light)',
        accentColorDark: 'var(--color-product-cohorts-dark)',
        hedgehog: HedgehogParty,
        text: {
            'needs-setup': {
                headline: 'Save the group of people you keep filtering for',
                lead: 'A cohort is a set of people who match conditions you pick, like signed up last week, on a paid plan, or viewed pricing without converting. Define it once and reuse it as a filter in insights, a target for a flag, or an audience for a survey.',
            },
        },
        primaryAction: {
            label: 'Create your first cohort',
            to: urls.cohort('new'),
            dataAttr: 'create-cohort',
        },
        skippable: false,
        docsUrl: 'https://posthog.com/docs/data/cohorts',
        previewLabel: 'Your cohorts, once created',
        Preview: CohortsPreview,
    },
}

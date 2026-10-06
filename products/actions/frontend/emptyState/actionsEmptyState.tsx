import * as cursorPng from '@posthog/brand/hoggies/png/cursor'
import { IconCursorClick } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ActionsPreview } from './ActionsPreview'
import { actionsSetupLogic } from './actionsSetupLogic'

const HedgehogCursor = pngHoggie(cursorPng)

export const actionsEmptyState: SceneProductEmptyState = {
    statusLogic: actionsSetupLogic,
    config: {
        productKey: ProductKey.ACTIONS,
        productName: 'Actions',
        icon: <IconCursorClick />,
        accentColor: 'var(--color-product-actions-light)',
        accentColorDark: 'var(--color-product-actions-dark)',
        hedgehog: HedgehogCursor,
        text: {
            'needs-setup': {
                headline: 'Give the clicks that matter a name',
                lead: 'An action groups several events under one name, so "Signed up" can cover the button on your pricing page and the one in your nav. Point it at an element, a page, or an event you already send, then use that one name in insights, funnels, and cohorts.',
            },
        },
        primaryAction: {
            label: 'Create your first action',
            to: urls.createAction(),
            dataAttr: 'create-action',
            accessControl: {
                resourceType: AccessControlResourceType.Action,
                minAccessLevel: AccessControlLevel.Editor,
            },
        },
        skippable: false,
        docsUrl: 'https://posthog.com/docs/data/actions',
        previewLabel: 'Your actions, once created',
        Preview: ActionsPreview,
    },
}

import * as reporterPng from '@posthog/brand/hoggies/png/reporter'
import { IconNotification } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { AnnotationsPreview } from './AnnotationsPreview'
import { AnnotationsPrimaryAction } from './AnnotationsPrimaryAction'
import { annotationsSetupLogic } from './annotationsSetupLogic'

const HedgehogReporter = pngHoggie(reporterPng)

export const annotationsEmptyState: SceneProductEmptyState = {
    statusLogic: annotationsSetupLogic,
    config: {
        productKey: ProductKey.ANNOTATIONS,
        productName: 'Annotations',
        icon: <IconNotification />,
        accentColor: 'var(--color-product-annotations-light)',
        accentColorDark: 'var(--color-product-annotations-dark)',
        hedgehog: HedgehogReporter,
        text: {
            'needs-setup': {
                headline: 'Mark the days that explain your charts',
                lead: 'A spike or a drop usually has a cause: a release, a pricing change, a campaign. Write it down once as an annotation and it shows up on every chart covering that date, so the next person to open the graph reads the reason instead of guessing.',
            },
        },
        PrimaryAction: AnnotationsPrimaryAction,
        skippable: false,
        docsUrl: 'https://posthog.com/docs/data/annotations',
        previewLabel: 'Your annotations, once created',
        Preview: AnnotationsPreview,
    },
}

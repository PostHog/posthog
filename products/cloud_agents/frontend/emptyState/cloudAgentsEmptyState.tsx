import { IconCloud } from '@posthog/icons'

import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import { CloudAgentsPreview } from './CloudAgentsPreview'
import { cloudAgentsSetupLogic } from './cloudAgentsSetupLogic'
import { EmptyStateApiExample } from './EmptyStateApiExample'
import { EmptyStateTabs } from './EmptyStateTabs'
import { StartFirstRunButton } from './StartFirstRunButton'

export const cloudAgentsEmptyState: SceneProductEmptyState = {
    statusLogic: cloudAgentsSetupLogic,
    featureFlag: FEATURE_FLAGS.CLOUD_AGENTS,
    SceneNav: EmptyStateTabs,
    config: {
        productKey: ProductKey.CLOUD_AGENTS,
        productName: 'Cloud agents',
        icon: <IconCloud />,
        accentColor: 'var(--color-product-tasks-light)',
        accentColorDark: 'var(--color-product-tasks-dark)',
        text: {
            'needs-setup': {
                headline: 'Send a prompt, get a pull request',
                lead: 'Give a coding agent a prompt and a repository. It works in its own cloud sandbox and opens a pull request when it is done. You pay for the time the sandbox runs, billed per second, and you can see what each run costs. Bring your own ChatGPT or Claude subscription, or let PostHog provide the model.',
            },
        },
        PrimaryAction: StartFirstRunButton,
        SetupActions: EmptyStateApiExample,
        skippable: false,
        previewLabel: 'Your runs, once started',
        Preview: CloudAgentsPreview,
    },
}

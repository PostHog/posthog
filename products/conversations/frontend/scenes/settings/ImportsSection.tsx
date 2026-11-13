import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { IntercomImportSection } from './IntercomImportSection'
import { PylonImportSection } from './PylonImportSection'
import { ZendeskImportSection } from './ZendeskImportSection'

type ImportTabKey = 'zendesk' | 'intercom' | 'pylon'

const DEFAULT_IMPORT_TAB: ImportTabKey = 'zendesk'

export function ImportsSection(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { hashParams, searchParams } = useValues(router)
    const intercomEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_INTERCOM_IMPORT]
    const pylonEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_PYLON_IMPORT]

    const activeTab = (hashParams.import as ImportTabKey | undefined) ?? DEFAULT_IMPORT_TAB

    const setTab = (tab: ImportTabKey): void => {
        router.actions.replace(urls.supportSettings(), searchParams, { ...hashParams, import: tab })
    }

    return (
        <LemonTabs
            activeKey={activeTab}
            onChange={(key) => setTab(key)}
            tabs={[
                {
                    key: 'zendesk',
                    label: 'Zendesk',
                    content: <ZendeskImportSection />,
                },
                intercomEnabled && {
                    key: 'intercom' as const,
                    label: 'Intercom',
                    content: <IntercomImportSection />,
                },
                pylonEnabled && {
                    key: 'pylon' as const,
                    label: 'Pylon',
                    content: <PylonImportSection />,
                },
            ]}
        />
    )
}

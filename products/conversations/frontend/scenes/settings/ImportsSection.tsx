import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { IntercomImportSection } from './IntercomImportSection'
import { PylonImportSection } from './PylonImportSection'
import { ZendeskImportSection } from './ZendeskImportSection'

type ImportTabKey = 'zendesk' | 'intercom' | 'pylon'

const DEFAULT_IMPORT_TAB: ImportTabKey = 'zendesk'

export function ImportsSection(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { location, hashParams, searchParams } = useValues(router)
    const intercomEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_INTERCOM_IMPORT]
    const pylonEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_PYLON_IMPORT]

    const tabs: (LemonTab<ImportTabKey> | false)[] = [
        {
            key: 'zendesk',
            label: 'Zendesk',
            content: <ZendeskImportSection />,
        },
        intercomEnabled && {
            key: 'intercom',
            label: 'Intercom',
            content: <IntercomImportSection />,
        },
        pylonEnabled && {
            key: 'pylon',
            label: 'Pylon',
            content: <PylonImportSection />,
        },
    ]
    const activeTab =
        tabs.find((tab): tab is LemonTab<ImportTabKey> => !!tab && tab.key === hashParams.import)?.key ??
        DEFAULT_IMPORT_TAB

    const setTab = (tab: ImportTabKey): void => {
        router.actions.replace(location.pathname, searchParams, { ...hashParams, import: tab })
    }

    return <LemonTabs activeKey={activeTab} onChange={(key) => setTab(key)} tabs={tabs} />
}

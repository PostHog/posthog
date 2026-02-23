import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonTable } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { browserLabTestsLogic } from './browserLabTestsLogic'
import type { BrowserLabTestType } from './types'

export const scene: SceneExport = {
    component: BrowserLabTestsScene,
    logic: browserLabTestsLogic,
}

export function BrowserLabTestsScene(): JSX.Element {
    const { browserLabTests, browserLabTestsLoading } = useValues(browserLabTestsLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Browser lab tests"
                resourceType={{ type: 'default' }}
                actions={
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={() => router.actions.push(urls.browserLabTest('new'))}
                    >
                        New test
                    </LemonButton>
                }
            />
            <LemonTable
                dataSource={browserLabTests}
                loading={browserLabTestsLoading}
                columns={[
                    {
                        title: 'Name',
                        dataIndex: 'name',
                        render: function RenderName(_, record: BrowserLabTestType) {
                            return (
                                <LemonTableLink
                                    to={urls.browserLabTest(record.id)}
                                    title={record.name}
                                    description={record.url}
                                />
                            )
                        },
                    },
                    {
                        title: 'URL',
                        dataIndex: 'url',
                    },
                    createdAtColumn() as any,
                ]}
                emptyState="No browser lab tests yet"
            />
        </SceneContent>
    )
}

export default BrowserLabTestsScene

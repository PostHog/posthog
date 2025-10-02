import { IconApps } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export function SchemaManagement(): JSX.Element {
    const columns: LemonTableColumns<any> = []

    return (
        <SceneContent>
            <SceneTitleSection
                name="Schema Management"
                description="Manage your data schemas and validation rules."
                resourceType={{
                    type: 'schema',
                    forceIcon: <IconApps />,
                }}
            />
            <SceneDivider />
            <div className="space-y-4">
                <div className="flex items-center gap-2">
                    <LemonInput type="search" placeholder="Search schema..." className="max-w-60" disabled />
                </div>
                <LemonTable columns={columns} dataSource={[]} loading={false} />
            </div>
        </SceneContent>
    )
}

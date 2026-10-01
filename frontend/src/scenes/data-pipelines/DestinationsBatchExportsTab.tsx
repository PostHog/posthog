import { useValues } from 'kea'

import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { BatchExportsList } from './batch-exports/BatchExportsList'
import { nonHogFunctionTemplatesLogic } from './utils/nonHogFunctionTemplatesLogic'

export function DestinationsBatchExportsTab(): JSX.Element {
    const { hogFunctionTemplatesBatchExports } = useValues(nonHogFunctionTemplatesLogic)

    return (
        <SceneContent>
            <SceneSection>
                <BatchExportsList />
            </SceneSection>
            <SceneDivider />
            <SceneSection title="Create a new batch export">
                <HogFunctionTemplateList
                    type="destination"
                    manualTemplates={hogFunctionTemplatesBatchExports}
                    manualTemplatesOnly
                />
            </SceneSection>
        </SceneContent>
    )
}

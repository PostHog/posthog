import { useActions, useValues } from 'kea'

import { IconArchive, IconDownload, IconInfo, IconPencil } from '@posthog/icons'

import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { DatasetTab, aiObservabilityDatasetLogic, isDataset } from './aiObservabilityDatasetLogic'

const RESOURCE_TYPE = 'dataset'

/** The saved dataset's menu bar. The caller renders it only behind the scene menu bar flag. */
export function DatasetSceneMenuBar({
    showTitleActions,
    onArchiveOrRestore,
}: {
    showTitleActions: boolean
    onArchiveOrRestore: () => void
}): JSX.Element | null {
    const {
        dataset,
        datasetLoading,
        isArchivingDataset,
        canEditDataset,
        canManageDataset,
        isHistoricalRevision,
        filters,
        datasetExportLoading,
        datasetExportDisabledReason,
    } = useValues(aiObservabilityDatasetLogic)
    const { editDataset, exportDataset, setActiveTab } = useActions(aiObservabilityDatasetLogic)
    const fileActions = useSceneFileActions(RESOURCE_TYPE)

    if (!isDataset(dataset)) {
        return null
    }
    const canChangeDatasetStatus = canManageDataset && !isHistoricalRevision
    const statusDisabledReason = datasetLoading
        ? 'Dataset is loading'
        : isArchivingDataset
          ? 'Dataset status is changing'
          : undefined

    const actions: SceneAction[] = [
        ...fileActions,
        {
            group: 'file',
            section: 'export',
            id: `${RESOURCE_TYPE}-menubar-export`,
            label: 'Export',
            icon: <IconDownload />,
            disabledReason: datasetExportDisabledReason ?? (datasetExportLoading ? 'Exporting dataset' : undefined),
            onSelect: () => exportDataset(filters.revision ?? undefined),
        },
        ...(canChangeDatasetStatus
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-${dataset.archived ? 'unarchive' : 'archive'}`,
                      label: dataset.archived ? 'Unarchive' : 'Archive',
                      icon: <IconArchive />,
                      destructive: !dataset.archived,
                      disabledReason: statusDisabledReason,
                      onSelect: onArchiveOrRestore,
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showTitleActions && canEditDataset
            ? ([
                  {
                      group: 'edit',
                      id: `${RESOURCE_TYPE}-menubar-edit`,
                      label: 'Edit',
                      icon: <IconPencil />,
                      onSelect: () => editDataset(true),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showTitleActions
            ? ([
                  {
                      group: 'view',
                      id: `${RESOURCE_TYPE}-menubar-details`,
                      label: 'Details',
                      icon: <IconInfo />,
                      onSelect: () => setActiveTab(DatasetTab.Metadata),
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}

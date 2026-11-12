import { useActions, useValues } from 'kea'

import { IconEllipsis, IconInfo, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonMenu, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { SandboxCustomImageDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { CloudImageModal } from './CloudImageModal'
import { cloudImagesLogic } from './cloudImagesLogic'
import { cloudImageStatus } from './cloudImageStatus'

export function CloudImagesSettings(): JSX.Element {
    const { images, imagesLoading, imagesFailed, unavailable, buildingImageIds, buildDisabledReason } =
        useValues(cloudImagesLogic)
    const { loadImages, startNewImage, deleteImage, buildImage } = useActions(cloudImagesLogic)

    if (unavailable) {
        return (
            <p className="text-secondary mb-0 max-w-200">
                Custom images are not available for this project yet. Cloud runs install what they need on each run.
            </p>
        )
    }

    const confirmDelete = (image: SandboxCustomImageDTOApi): void => {
        LemonDialog.open({
            title: `Delete "${image.name}"?`,
            description: 'Environments that use this image go back to the default image.',
            primaryButton: { children: 'Delete', status: 'danger', onClick: () => deleteImage(image) },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex flex-col gap-2 max-w-200">
            <div className="flex">
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={startNewImage}
                    data-attr="cloud-image-new"
                >
                    New image
                </LemonButton>
            </div>
            {imagesFailed ? (
                <LemonBanner
                    type="warning"
                    action={{ children: 'Try again', onClick: loadImages, loading: imagesLoading }}
                >
                    The images did not load.
                </LemonBanner>
            ) : (
                <LemonTable
                    size="small"
                    loading={imagesLoading && images === null}
                    dataSource={images ?? []}
                    rowKey="id"
                    emptyState="No images yet. Cloud runs install what they need on each run until you build one."
                    columns={[
                        {
                            title: 'Name',
                            key: 'name',
                            render: (_, image) => <span className="font-semibold">{image.name}</span>,
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: (_, image) => {
                                const { label, type } = cloudImageStatus(image.status)
                                return image.error &&
                                    (image.status === 'scan_failed' || image.status === 'build_failed') ? (
                                    <Tooltip title={<div className="whitespace-pre-wrap">{image.error}</div>}>
                                        <LemonTag size="small" type={type} icon={<IconInfo />} tabIndex={0}>
                                            {label}
                                        </LemonTag>
                                    </Tooltip>
                                ) : (
                                    <LemonTag size="small" type={type}>
                                        {label}
                                    </LemonTag>
                                )
                            },
                        },
                        {
                            title: 'Used by',
                            key: 'private',
                            render: (_, image) => (
                                <LemonTag size="small" type={image.private ? 'muted' : 'warning'}>
                                    {image.private ? 'Only you' : 'Everyone in this project'}
                                </LemonTag>
                            ),
                        },
                        {
                            key: 'build',
                            width: 0,
                            render: (_, image) => (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() => buildImage(image)}
                                    loading={buildingImageIds.includes(image.id)}
                                    disabledReason={buildDisabledReason(image)}
                                    data-attr="cloud-image-build"
                                    className="whitespace-nowrap"
                                >
                                    Save & build
                                </LemonButton>
                            ),
                        },
                        {
                            key: 'actions',
                            width: 0,
                            render: (_, image) => (
                                <LemonMenu
                                    items={[
                                        image.builder_task_id
                                            ? { label: 'Open builder task', to: urls.taskDetail(image.builder_task_id) }
                                            : null,
                                        { label: 'Delete', status: 'danger', onClick: () => confirmDelete(image) },
                                    ]}
                                >
                                    <LemonButton
                                        size="small"
                                        icon={<IconEllipsis />}
                                        aria-label={`Actions for ${image.name}`}
                                    />
                                </LemonMenu>
                            ),
                        },
                    ]}
                />
            )}
            <CloudImageModal />
        </div>
    )
}

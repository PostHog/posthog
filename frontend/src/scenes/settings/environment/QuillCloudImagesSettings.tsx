import { useActions, useValues } from 'kea'

import { IconEllipsis, IconInfo, IconPlus } from '@posthog/icons'
import type { LemonTagType } from '@posthog/lemon-ui'
import {
    Badge,
    Button,
    DataTable,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { QuillMenuItems } from 'scenes/session-recordings/playlist/QuillMenuItems'

import type { SandboxCustomImageDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { cloudImagesLogic } from './cloudImagesLogic'
import { cloudImageStatus } from './cloudImageStatus'
import { QuillCloudImageModal } from './QuillCloudImageModal'
import { QuillLoadFailedCallout } from './QuillLoadFailedCallout'

const STATUS_BADGE_VARIANT: Partial<Record<LemonTagType, 'default' | 'warning' | 'destructive' | 'success'>> = {
    warning: 'warning',
    danger: 'destructive',
    success: 'success',
}

function ImageStatusBadge({ image }: { image: SandboxCustomImageDTOApi }): JSX.Element {
    const { label, type } = cloudImageStatus(image.status)
    const variant = STATUS_BADGE_VARIANT[type] ?? 'default'

    if (image.error && (image.status === 'scan_failed' || image.status === 'build_failed')) {
        return (
            <Tooltip>
                <TooltipTrigger render={<Badge variant={variant} tabIndex={0} />}>
                    <IconInfo />
                    {label}
                </TooltipTrigger>
                <TooltipContent className="max-w-80">
                    <div className="whitespace-pre-wrap">{image.error}</div>
                </TooltipContent>
            </Tooltip>
        )
    }

    return <Badge variant={variant}>{label}</Badge>
}

export function QuillCloudImagesSettings({
    actionItems,
}: {
    actionItems: (image: SandboxCustomImageDTOApi) => LemonMenuItems
}): JSX.Element {
    const { images, imagesLoading, imagesFailed, buildingImageIds, buildDisabledReason } = useValues(cloudImagesLogic)
    const { loadImages, startNewImage, buildImage } = useActions(cloudImagesLogic)

    return (
        <div className="flex flex-col gap-2 max-w-200">
            <div className="flex">
                <Button variant="primary" onClick={startNewImage} data-attr="cloud-image-new">
                    <IconPlus />
                    New image
                </Button>
            </div>
            {imagesFailed ? (
                <QuillLoadFailedCallout
                    message="The images did not load."
                    onRetry={loadImages}
                    loading={imagesLoading}
                />
            ) : imagesLoading && images === null ? (
                <Skeleton className="h-24 w-full" />
            ) : (
                <DataTable
                    size="sm"
                    fullWidth
                    data={images ?? []}
                    getRowId={(image) => image.id}
                    empty={
                        <Empty>
                            <EmptyHeader>
                                <EmptyDescription>
                                    No images yet. Cloud runs install what they need on each run until you build one.
                                </EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    }
                    columns={[
                        {
                            id: 'name',
                            header: 'Name',
                            enableSorting: false,
                            meta: { expand: true },
                            cell: ({ row }) => (
                                <Text size="xs" weight="semibold" render={<span />}>
                                    {row.original.name}
                                </Text>
                            ),
                        },
                        {
                            id: 'status',
                            header: 'Status',
                            enableSorting: false,
                            cell: ({ row }) => <ImageStatusBadge image={row.original} />,
                        },
                        {
                            id: 'private',
                            header: 'Used by',
                            enableSorting: false,
                            cell: ({ row }) => (
                                <Badge variant={row.original.private ? 'default' : 'warning'}>
                                    {row.original.private ? 'Only you' : 'Everyone in this project'}
                                </Badge>
                            ),
                        },
                        {
                            id: 'build',
                            header: '',
                            enableSorting: false,
                            cell: ({ row }) => (
                                <Button
                                    variant="outline"
                                    onClick={() => buildImage(row.original)}
                                    loading={buildingImageIds.includes(row.original.id)}
                                    disabledReason={buildDisabledReason(row.original)}
                                    data-attr="cloud-image-build"
                                    className="whitespace-nowrap"
                                >
                                    Save & build
                                </Button>
                            ),
                        },
                        {
                            id: 'actions',
                            header: '',
                            enableSorting: false,
                            meta: { align: 'right' },
                            cell: ({ row }) => (
                                <DropdownMenu>
                                    <DropdownMenuTrigger
                                        render={
                                            <Button
                                                size="icon"
                                                aria-label={`Actions for ${row.original.name}`}
                                                tooltip={`Actions for ${row.original.name}`}
                                            />
                                        }
                                    >
                                        <IconEllipsis />
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end">
                                        <QuillMenuItems items={actionItems(row.original)} />
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            ),
                        },
                    ]}
                />
            )}
            <QuillCloudImageModal />
        </div>
    )
}

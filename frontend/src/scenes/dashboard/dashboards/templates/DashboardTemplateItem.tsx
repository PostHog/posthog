import clsx from 'clsx'
import { useId } from 'react'

import { IconBuilding, IconHeartFilled } from '@posthog/icons'

import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { DashboardTemplateType } from '~/types'

/** Reset `<button>` defaults; omit `border-0` or it can override `border` / `border-border` in the compiled sheet. */
const templateItemButtonResetClass = 'appearance-none p-0 m-0 w-full cursor-pointer text-left font-inherit'

const templateItemFocusClass =
    'outline-none focus-visible:ring-2 focus-visible:ring-primary-3000 focus-visible:ring-offset-2'

const noCoverRowHover =
    'hover:border-primary-3000-hover hover:shadow-md hover:-translate-y-px active:translate-y-0 active:shadow-sm'

const buildingIconShellClass =
    'flex shrink-0 items-center justify-center rounded-md bg-fill-secondary text-secondary transition-colors group-hover:text-primary'

const featuredImageColumnClass =
    'relative shrink-0 w-40 sm:w-44 h-[132px] overflow-hidden transition-transform duration-300 ease-out will-change-transform group-hover:scale-[1.04]'

export type TemplateItemSize = 'default' | 'large'

export interface DashboardTemplateItemProps {
    template: Pick<DashboardTemplateType, 'template_name' | 'dashboard_description' | 'image_url' | 'tags'>
    onClick: () => void
    index: number
    'data-attr': string
    /** Larger card + image for featured row experiment */
    size?: TemplateItemSize
    showFavourite?: boolean
    /** When false, omit cover art (e.g. project templates with no `image_url`). */
    showCover?: boolean
}

function TemplateItemBuildingGlyph({ size }: { size: 'sm' | 'lg' }): JSX.Element {
    const isLarge = size === 'lg'
    return (
        <span className={clsx(buildingIconShellClass, isLarge ? 'size-12' : 'size-10')} aria-hidden>
            <IconBuilding className={isLarge ? 'size-6' : 'size-5'} />
        </span>
    )
}

function TemplateItemTitleDescription({
    titleId,
    template,
    wrapClassName,
    titleClassName,
    descriptionClassName,
}: {
    titleId: string
    template: Pick<DashboardTemplateType, 'template_name' | 'dashboard_description'>
    wrapClassName: string
    titleClassName: string
    descriptionClassName: string
}): JSX.Element {
    return (
        <div className={wrapClassName}>
            <h5 id={titleId} className={titleClassName}>
                {template?.template_name}
            </h5>
            <p className={descriptionClassName}>{template?.dashboard_description ?? ' '}</p>
        </div>
    )
}

function noCoverButtonClass(isLarge: boolean): string {
    return clsx(
        templateItemButtonResetClass,
        'group TemplateItem flex flex-row items-start rounded-md border border-border bg-bg-light text-left shadow-sm transition-all duration-200',
        noCoverRowHover,
        templateItemFocusClass,
        isLarge ? 'relative min-h-0 gap-4 p-4' : 'gap-3 p-3'
    )
}

export function TemplateItem({
    template,
    onClick,
    index,
    'data-attr': dataAttr,
    size = 'default',
    showFavourite = false,
    showCover = true,
}: DashboardTemplateItemProps): JSX.Element {
    const titleId = useId()
    const isLarge = size === 'large'
    const imageHeightClass = 'h-30'

    const favouriteHeart = showFavourite ? (
        <Tooltip title="Users love this template">
            <span className="absolute top-2 right-2 z-20 inline-flex pointer-events-auto">
                <IconHeartFilled className="text-danger size-7" />
            </span>
        </Tooltip>
    ) : null

    if (!showCover) {
        return (
            <button
                type="button"
                className={noCoverButtonClass(isLarge)}
                onClick={onClick}
                data-attr={dataAttr}
                aria-labelledby={titleId}
            >
                {isLarge ? favouriteHeart : null}
                <TemplateItemBuildingGlyph size={isLarge ? 'lg' : 'sm'} />
                <TemplateItemTitleDescription
                    titleId={titleId}
                    template={template}
                    wrapClassName={clsx('min-w-0 flex-1 flex flex-col', isLarge ? 'gap-1' : 'gap-0.5')}
                    titleClassName={clsx('min-w-0 font-semibold leading-snug', isLarge ? 'text-base' : 'text-sm')}
                    descriptionClassName={clsx(
                        'text-secondary m-0 group-hover:line-clamp-none',
                        isLarge ? 'text-sm line-clamp-4' : 'text-xs line-clamp-2'
                    )}
                />
            </button>
        )
    }

    if (isLarge) {
        return (
            <button
                type="button"
                className={clsx(
                    templateItemButtonResetClass,
                    'group border border-border rounded TemplateItem flex flex-row',
                    'bg-bg-light shadow-sm transition-all duration-200 ease-out relative overflow-hidden min-h-[132px]',
                    'hover:border-primary-3000-hover hover:shadow-md hover:-translate-y-1',
                    'hover:ring-1 hover:ring-primary/25',
                    'active:translate-y-0 active:shadow-sm active:ring-0',
                    templateItemFocusClass
                )}
                onClick={onClick}
                data-attr={dataAttr}
                aria-labelledby={titleId}
            >
                <div className={featuredImageColumnClass}>
                    <FallbackCoverImage
                        src={template?.image_url}
                        alt="cover photo"
                        index={index}
                        imageClassName="h-full w-full object-cover"
                    />
                    {favouriteHeart}
                </div>

                <TemplateItemTitleDescription
                    titleId={titleId}
                    template={template}
                    wrapClassName="flex-1 min-w-0 px-3 py-2 flex flex-col justify-center gap-1 z-10 overflow-y-auto transition-colors duration-200 group-hover:bg-primary-highlight/25"
                    titleClassName="min-w-0 text-base leading-tight"
                    descriptionClassName="text-secondary text-sm m-0 line-clamp-3 group-hover:line-clamp-none"
                />
            </button>
        )
    }

    return (
        <button
            type="button"
            className={clsx(
                templateItemButtonResetClass,
                'group border rounded TemplateItem flex flex-col transition-all relative',
                'h-[210px]',
                templateItemFocusClass
            )}
            onClick={onClick}
            data-attr={dataAttr}
            aria-labelledby={titleId}
        >
            <div className="transition-all w-full overflow-hidden z-0 h-30 min-h-30 group-hover:h-4 group-hover:min-h-4">
                <FallbackCoverImage
                    src={template?.image_url}
                    alt="cover photo"
                    index={index}
                    imageClassName={imageHeightClass}
                />
            </div>

            {favouriteHeart}

            <TemplateItemTitleDescription
                titleId={titleId}
                template={template}
                wrapClassName="px-2 py-1 overflow-y-auto grow z-10 flex flex-col gap-1"
                titleClassName="min-w-0"
                descriptionClassName="text-secondary text-xs line-clamp-2 group-hover:line-clamp-none"
            />
        </button>
    )
}

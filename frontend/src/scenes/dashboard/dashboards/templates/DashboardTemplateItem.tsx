import clsx from 'clsx'
import { useState } from 'react'

import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'

import { DashboardTemplateType } from '~/types'

export interface DashboardTemplateItemProps {
    template: Pick<DashboardTemplateType, 'template_name' | 'dashboard_description' | 'image_url' | 'tags'>
    onClick: () => void
    index: number
    'data-attr': string
}

export function TemplateItem({
    template,
    onClick,
    index,
    'data-attr': dataAttr,
}: DashboardTemplateItemProps): JSX.Element {
    const [isHovering, setIsHovering] = useState(false)

    return (
        <div
            className="cursor-pointer border rounded TemplateItem flex flex-col transition-all w-full h-[210px]"
            onClick={onClick}
            onMouseEnter={() => setIsHovering(true)}
            onMouseLeave={() => setIsHovering(false)}
            data-attr={dataAttr}
        >
            <div
                className={clsx('transition-all w-full overflow-hidden', isHovering ? 'h-4 min-h-4' : 'h-30 min-h-30')}
            >
                <FallbackCoverImage src={template?.image_url} alt="cover photo" index={index} imageClassName="h-30" />
            </div>

            <h5 className="px-2 mb-1 min-w-0">{template?.template_name}</h5>
            <div className="px-2 py-1 overflow-y-auto grow">
                <p className={clsx('text-secondary text-xs', isHovering ? '' : 'line-clamp-2')}>
                    {template?.dashboard_description ?? ' '}
                </p>
            </div>
        </div>
    )
}

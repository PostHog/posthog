import React from 'react'
import { AimOutlined } from '@ant-design/icons'
import { ActionSelectInfo } from '../../ActionSelectInfo'
import { RenderInfoProps } from 'lib/components/SelectBox'
import { Link } from 'lib/components/Link'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

export function ActionInfo({ item }: RenderInfoProps): JSX.Element {
    if (item.renderInfo) {
        return item.renderInfo({ item })
    }
    return (
        <>
            <AimOutlined /> Actions
            <Link
                to={`/action/${item.id}#backTo=Insights&backToURL=${encodeURIComponent(
                    window.location.pathname + window.location.search
                )}`}
                style={{ float: 'right' }}
                tabIndex={-1}
            >
                edit
            </Link>
            <br />
            <h3>
                <PropertyKeyInfo value={item.name} />
            </h3>
            {item.action && <ActionSelectInfo entity={item.action} />}
        </>
    )
}

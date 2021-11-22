import React from 'react'
import { AimOutlined } from '@ant-design/icons'
import { ActionSelectInfo } from '../../ActionSelectInfo'
import { RenderInfoProps } from 'lib/components/SelectBox'
import { Link } from 'lib/components/Link'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { urls } from 'scenes/urls'

export function ActionInfo({ item }: RenderInfoProps): JSX.Element {
    if (item.renderInfo) {
        return item.renderInfo({ item })
    }
    return (
        <>
            <AimOutlined /> Actions
            {item.id && (
                <Link to={urls.action(item.id)} style={{ float: 'right' }} tabIndex={-1}>
                    edit
                </Link>
            )}
            <br />
            <h3>
                <PropertyKeyInfo value={item.name} />
            </h3>
            {item.action && <ActionSelectInfo entity={item.action} />}
        </>
    )
}

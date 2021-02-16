import React from 'react'
import { Button } from 'antd'
import { Link, LinkProps } from 'lib/components/Link'

export function LinkButton(props: LinkProps & { icon?: React.ReactNode }): JSX.Element {
    const { icon, ...linkProps } = props
    return <Link {...linkProps} tag={<Button icon={icon} />} />
}

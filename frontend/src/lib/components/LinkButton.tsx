import React from 'react'
import { Button } from 'antd'
import { Link, LinkProps } from 'lib/components/Link'

export function LinkButton(props: LinkProps): JSX.Element {
    return <Link {...props} tag={Button} />
}

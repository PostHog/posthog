import React, { HTMLProps } from 'react'
import { Button } from 'antd'
import { Link } from 'lib/components/Link'

export function LinkButton(props: HTMLProps<HTMLAnchorElement>): JSX.Element {
    return <Link {...props} tag={Button} />
}

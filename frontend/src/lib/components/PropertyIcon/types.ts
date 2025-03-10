import { HTMLAttributes } from 'react'

export interface PropertyIconProps {
    property: string
    value?: string
    className?: string
    onClick?: HTMLAttributes<HTMLDivElement>['onClick']
}

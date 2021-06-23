import React from 'react'
import { SelectGradientOverflowProps } from 'lib/components/SelectGradientOverflow'
import { TabbedPropertyFilter } from './TabbedPropertyFilter'
import { UnifiedPropertyFilter } from './UnifiedPropertyFilter'

export interface PropertyFilterInternalProps {
    index: number
    onComplete: CallableFunction
    selectProps: Partial<SelectGradientOverflowProps>
}

export interface PropertyFilterProps extends PropertyFilterInternalProps {
    variant: 'tabs' | 'unified'
}

export function PropertyFilter({ variant = 'tabs', ...props }: PropertyFilterProps): JSX.Element {
    switch (variant) {
        case 'unified':
            return <UnifiedPropertyFilter {...props} />
        case 'tabs':
            return <TabbedPropertyFilter {...props} />
    }
}

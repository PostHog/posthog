import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import * as React from 'react'

import { cn } from './lib/utils'
import './menu-label.css'

// Section label for menus/lists. Defaults to a <div>; pass render=<label /> to
// bind it to a control.
function MenuLabel({ className, render, ...props }: useRender.ComponentProps<'div'>): React.ReactElement {
    return useRender({
        defaultTagName: 'div',
        props: mergeProps<'div'>(
            {
                'data-quill': '',
                'data-slot': 'menu-label',
                className: cn('quill-menu-label', className),
            } as Omit<React.ComponentProps<'div'>, 'ref'>,
            props
        ),
        render,
    })
}

export { MenuLabel }

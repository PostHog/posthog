import './AnimatedBackButton.scss'

import clsx from 'clsx'

import { useExitTransition } from 'lib/hooks/useExitTransition'

export function AnimatedBackButton({
    children,
    in: inProp,
}: React.PropsWithChildren<{ in: boolean }>): JSX.Element | null {
    const { mounted, visible } = useExitTransition(inProp, 100)

    if (!mounted) {
        return null
    }

    return (
        <div className={clsx('shrink-0 overflow-hidden MaxBackButton', visible && 'MaxBackButton--visible')}>
            {children}
        </div>
    )
}

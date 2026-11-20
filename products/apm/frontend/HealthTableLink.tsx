import { Link, LinkProps } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

/**
 * A service or endpoint name that opens its page. LemonTable recolors links to the body text color,
 * so this restores the standard Lemon link color to show the name can be clicked.
 */
export function HealthTableLink({ className, ...props }: LinkProps): JSX.Element {
    return <Link {...props} className={cn('font-semibold !text-accent hover:!text-accent-hover', className)} />
}

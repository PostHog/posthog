import clsx from 'clsx'
import './LemonTableLoader.scss'

export function LemonTableLoader({ loading = false }: { loading?: boolean }): JSX.Element {
    return <div className={clsx('LemonTableLoader', loading && 'LemonTableLoader--loading')} />
}

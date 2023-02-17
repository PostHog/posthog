import { CSSTransition } from 'react-transition-group'
import './LemonTableLoader.scss'

export function LemonTableLoader({ loading = false }: { loading?: boolean }): JSX.Element {
    return (
        <CSSTransition in={loading} timeout={200} classNames="LemonTableLoader-" appear mountOnEnter unmountOnExit>
            <div className="LemonTableLoader" />
        </CSSTransition>
    )
}

import { NotFound } from 'lib/components/NotFound'

export function Error404(): JSX.Element {
    return (
        <NotFound
            object="page"
            caption="The page you were looking for is not here. Please use the navigation and try again."
        />
    )
}

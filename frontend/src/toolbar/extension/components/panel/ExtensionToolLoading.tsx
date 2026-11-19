import { Spinner } from 'lib/lemon-ui/Spinner'

export function ExtensionToolLoading(): JSX.Element {
    return (
        <div className="flex justify-center p-4">
            <Spinner className="text-2xl" />
        </div>
    )
}

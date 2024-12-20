export function AccessDenied(): JSX.Element {
    return (
        <div className="flex flex-col items-center max-w-2xl p-4 my-24 mx-auto text-center">
            <h1 className="text-3xl font-bold mt-4 mb-0">Access denied</h1>
            <p className="text-sm mt-3 mb-0">
                You don't have access to this resource. Please contact support if you think this is a mistake.
            </p>
        </div>
    )
}

const NotebookIconHeading = ({ level }: { level: number }): JSX.Element => {
    return (
        <div className="text-base font-semibold">
            H<span className="text-xs font-bold">{level}</span>
        </div>
    )
}

export default NotebookIconHeading

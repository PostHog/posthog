const NotebookIconHeading = ({ level }: { level: number }): JSX.Element => {
    return (
        <div style={{ fontSize: 16, fontWeight: '600' }}>
            H<span className="text-xs font-bold">{level}</span>
        </div>
    )
}

export default NotebookIconHeading

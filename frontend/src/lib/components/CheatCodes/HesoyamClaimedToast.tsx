export function HesoyamClaimedToast(): JSX.Element {
    return (
        <>
            <style>{`
                @keyframes hesoyam-fill {
                    0% { width: 55%; }
                    100% { width: 85%; }
                }
                @keyframes hesoyam-bonus-pop {
                    0% { opacity: 0; transform: scale(0.5) translateY(2px); }
                    60% { opacity: 1; transform: scale(1.15) translateY(-1px); }
                    100% { opacity: 1; transform: scale(1) translateY(0); }
                }
            `}</style>
            <div className="flex items-center gap-3 font-mono" style={{ minWidth: 280 }}>
                <span className="text-xs font-bold uppercase tracking-wider opacity-90">Total respect</span>
                <div className="flex-1 flex items-center gap-1.5">
                    <div
                        className="h-3 rounded-sm flex-1 overflow-hidden"
                        style={{ backgroundColor: 'rgba(255,255,255,0.15)' }}
                    >
                        <div
                            className="h-full rounded-sm"
                            style={{
                                width: '85%',
                                background: 'linear-gradient(90deg, #4b9c4b 0%, #6bcf6b 100%)',
                                animation: 'hesoyam-fill 0.8s ease-out',
                            }}
                        />
                    </div>
                    <span className="text-xs font-bold opacity-70">+</span>
                </div>
                <span
                    className="font-bold"
                    style={{
                        color: '#5dde5d',
                        fontSize: '0.8125rem',
                        lineHeight: 1,
                        textShadow: '0 0 8px rgba(93, 222, 93, 0.5)',
                        animation: 'hesoyam-bonus-pop 0.5s ease-out 0.7s both',
                    }}
                >
                    +$5
                </span>
            </div>
        </>
    )
}

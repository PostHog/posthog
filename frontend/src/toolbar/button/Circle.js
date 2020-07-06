import React from 'react'

export function Circle({
    width,
    x,
    y,
    extensionPercentage = 1,
    distance,
    rotation = 0,
    content,
    className,
    top,
    left,
    right,
    bottom,
    zIndex,
    animate,
    animationStart = rotation + 0,
    animationEnd = rotation + 360,
    animationId,
    animationDuration = 15,
    label,
    labelPosition = 'bottom',
    style = {},
    labelStyle = {},
    children,
    rootNode = false,
    accumulatedRotation = 0,
    rotationFixer = () => 0,
    ...props
}) {
    const useCoords = typeof x !== 'undefined' && typeof y !== 'undefined'
    const usedDistance = useCoords ? Math.sqrt(x * x + y * y) * extensionPercentage : distance * extensionPercentage
    let usedRotation = (useCoords ? Math.atan2(y, x) * (180 / Math.PI) : rotation) - accumulatedRotation
    usedRotation = usedRotation + rotationFixer(usedRotation)

    const clonedChildren = React.Children.toArray(children).map((child) =>
        React.cloneElement(child, {
            accumulatedRotation: usedRotation + accumulatedRotation,
        })
    )

    return (
        <>
            {animate ? (
                <style>{`	
@keyframes circle-spin-${animationId} { 
    0% { transform: rotate(${animationStart}deg) translate(${usedDistance}px, 0px); } 	
    100% { transform: rotate(${animationEnd}deg) translate(${usedDistance}px, 0px); }
}
@keyframes circle-spin-${animationId}-reverse { 	          
    0% { transform: rotate(${-animationStart}deg); } 	              
    100% { transform: rotate(${-animationEnd}deg); } 	      
}
                `}</style>
            ) : null}
            <div
                className="circle-transformer"
                style={
                    rootNode
                        ? // we are the first circle
                          {
                              position: 'fixed',
                              top,
                              left,
                              right,
                              bottom,
                              zIndex,
                          }
                        : // we are an outer circle
                          {
                              zIndex,
                              position: 'absolute',
                              top: 0,
                              left: 0,
                              transform: `rotate(${usedRotation}deg) translate(${usedDistance}px, 0px)`,
                              transformOrigin: '0px 0px',
                              transition: 'transform ease 0.2s, opacity ease 0.2s',
                              willChange: 'transform',
                              animation: animate
                                  ? `circle-spin-${animationId} ${animationDuration}s linear infinite`
                                  : null,
                          }
                }
            >
                <div
                    className="circle-transform-correcter"
                    style={
                        rootNode
                            ? {}
                            : {
                                  transform: `rotate(${-usedRotation}deg)`,
                                  transformOrigin: '0 50%',
                                  transition: 'transform ease 0.2s, opacity ease 0.2s',
                                  willChange: 'transform',
                                  animation: animate
                                      ? `circle-spin-${animationId}-reverse ${animationDuration}s linear infinite`
                                      : null,
                              }
                    }
                >
                    <div
                        className={`circle-align-fixer`}
                        style={{
                            position: 'absolute',
                            transformOrigin: '50% 50%',
                            transform: `rotate(${-accumulatedRotation}deg)`,
                            transition: 'transform 0.2s',
                            zIndex,
                        }}
                    >
                        <div
                            className={`circle-button${className ? ` ${className}` : ''}`}
                            style={{
                                position: 'absolute',
                                width: width,
                                height: width,
                                marginLeft: -width / 2,
                                marginTop: -width / 2,
                                borderRadius: width / 2,
                                background: 'white',
                                boxShadow: '0 0 13px 4px rgba(0, 0, 0, 0.3)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                flexDirection: 'column',
                                zIndex,
                                ...style,
                            }}
                            {...props}
                        >
                            {content}
                        </div>
                        {label ? (
                            <div
                                className="circle-label"
                                style={{
                                    position: 'absolute',
                                    fontSize: '16px',
                                    lineHeight: '26px',
                                    ...(labelPosition === 'bottom'
                                        ? {
                                              width: 100,
                                              height: 20,
                                              marginLeft: -50,
                                              marginTop: width / 2,
                                              textAlign: 'center',
                                          }
                                        : labelPosition === 'left'
                                        ? {
                                              right: width / 2 + 8,
                                              marginTop: -13,
                                          }
                                        : labelPosition === 'right'
                                        ? {
                                              left: width / 2 + 8,
                                              marginTop: -13,
                                          }
                                        : {}),
                                    whiteSpace: 'nowrap',
                                    color: 'white',
                                    textShadow:
                                        'rgb(0, 0, 0) 0px 0px 2px, rgba(0,0,0,1) 0 0 2px, rgba(0,0,0,1) 0 0 10px, rgba(255,255,255,0.8) 0 0 40px, rgba(0,0,0,0.8) 0 0 20px',
                                    pointerEvents: 'none',
                                    zIndex,
                                    ...labelStyle,
                                }}
                            >
                                {label}
                            </div>
                        ) : null}
                    </div>
                </div>
                {clonedChildren}
            </div>
        </>
    )
}

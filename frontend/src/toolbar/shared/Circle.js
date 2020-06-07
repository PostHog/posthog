import React from 'react'

export function Circle({
    radius,
    distance,
    rotate,
    content,
    className,
    top,
    left,
    right,
    bottom,
    zIndex,
    style = {},
    children,
    rootNode = false,
    animate,
    animationId,
    animationDuration = 15,
    ...props
}) {
    return (
        <>
            {animate ? (
                <style>{`
@keyframes circle-spin-${animationId} { 
    0% { transform: rotate(${rotate + 0}deg) translate(${distance}px, 0px); } 
    100% { transform: rotate(${rotate + 360}deg) translate(${distance}px, 0px); } 
}
@keyframes circle-spin-${animationId}-reverse { 
    0% { transform: rotate(${-rotate}deg); } 
    100% { transform: rotate(${-(rotate + 360)}deg); } 
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
                          }
                        : // we are an outer circle
                          {
                              position: 'absolute',
                              top: 0,
                              left: 0,
                              transform: `rotate(${rotate}deg) translate(${distance}px, 0px)`,
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
                                  transform: `rotate(${-rotate}deg)`,
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
                        className={`circle-button${className ? ` ${className}` : ''}`}
                        style={{
                            position: 'absolute',
                            width: radius,
                            height: radius,
                            marginLeft: -radius / 2,
                            marginTop: -radius / 2,
                            transformOrigin: '50% 50%',
                            borderRadius: '100%',
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
                </div>
                {children}
            </div>
        </>
    )
}

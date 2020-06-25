import React from 'react'

export function Circle({
    width,
    distance,
    rotate,
    content,
    className,
    top,
    left,
    right,
    bottom,
    zIndex,
    animate,
    animationStart = rotate + 0,
    animationEnd = rotate + 360,
    animationId,
    animationDuration = 15,
    label,
    style = {},
    labelStyle = {},
    children,
    rootNode = false,
    ...props
}) {
    return (
        <>
            {animate ? (
                <style>{`	
@keyframes circle-spin-${animationId} { 
    0% { transform: rotate(${animationStart}deg) translate(${distance}px, 0px); } 	
    100% { transform: rotate(${animationEnd}deg) translate(${distance}px, 0px); }
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
                            width: width,
                            height: width,
                            marginLeft: -width / 2,
                            marginTop: -width / 2,
                            transformOrigin: '50% 50%',
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
                                width: 100,
                                height: 20,
                                marginLeft: -50,
                                marginTop: width / 2,
                                textAlign: 'center',
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
                {children}
            </div>
        </>
    )
}

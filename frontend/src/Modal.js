import React, { Component } from 'react'

export default class Modal extends Component {
    constructor(props) {
        super(props)
    
        this.state = {dismissed: false};
        this.dismiss = this.dismiss.bind(this)
        this.escFunction = this.escFunction.bind(this);
    }
    dismiss() {
        this.setState({dismissed: true});
        this.props.onDismiss && this.props.onDismiss();
    }
    escFunction(event){
        if(event.keyCode === 27) this.dismiss()
    }
    componentDidMount(){
        document.addEventListener("keydown", this.escFunction, false);
    }
    componentWillUnmount(){
        document.removeEventListener("keydown", this.escFunction, false);
    }
    render() {
        return !this.state.dismissed ? (<div>
            <div className="modal-backdrop fade show" onClick={this.dismiss}></div>
            <div className="modal fade show" style={{display: 'block'}} onClick={this.dismiss}>
                <div className="modal-dialog modal-lg" role="document">
                    <div className="modal-content" onClick={(event) => event.stopPropagation()}>
                        {this.props.title && <div className="modal-header">
                            <h5 className="modal-title" style={{width: '100%'}}>{typeof(this.props.title) === 'function' ? this.props.title() : this.props.title}</h5>
                            <button type="button" className="close" onClick={this.dismiss}>
                                <span style={{display: 'block'}}>×</span>
                            </button>
                        </div>}
                        <div className="modal-body" style={{fontSize: 15}}>
                            {!this.props.title && <button type="button" className="close" onClick={this.dismiss}>
                                <span style={{display: 'block'}}>×</span>
                            </button>}
                            {this.props.children}
                        </div>
                        {!this.props.hideFooter && <div className="modal-footer">
                            <button type="button" className="btn btn-outline-success" onClick={this.dismiss} data-dismiss="modal">{this.props.closeButton ? this.props.closeButton : 'Close'}</button>
                        </div>}
                    </div>
                </div>
            </div>
        </div>) : null;
    }
}

import{a as vn}from"/static/chunk-JSQDFFN3.js";import{a as gn}from"/static/chunk-YOTS5EBA.js";import{a as yn,b as xn}from"/static/chunk-K7LQKAJG.js";import{a as mn}from"/static/chunk-2ROB4QWU.js";import{a as hn}from"/static/chunk-IGYUTZ65.js";import{b as w,e as f,g as d,j as p}from"/static/chunk-SJXEOBQC.js";var qe=w((pl,He)=>{"use strict";f();p();d();He.exports=Be;var Se=Be.prototype;Se.space=null;Se.normal={};Se.property={};function Be(e,r,n){this.property=e,this.normal=r,n&&(this.space=n)}});var Ve=w((ml,Fe)=>{"use strict";f();p();d();var We=yn(),bn=qe();Fe.exports=wn;function wn(e){for(var r=e.length,n=[],o=[],a=-1,g,b;++a<r;)g=e[a],n.push(g.property),o.push(g.normal),b=g.space;return new bn(We.apply(null,n),We.apply(null,o),b)}});var me=w((wl,Ge)=>{"use strict";f();p();d();Ge.exports=Cn;function Cn(e){return e.toLowerCase()}});var Ae=w((Al,$e)=>{"use strict";f();p();d();$e.exports=Ke;var W=Ke.prototype;W.space=null;W.attribute=null;W.property=null;W.boolean=!1;W.booleanish=!1;W.overloadedBoolean=!1;W.number=!1;W.commaSeparated=!1;W.spaceSeparated=!1;W.commaOrSpaceSeparated=!1;W.mustUseProperty=!1;W.defined=!1;function Ke(e,r){this.property=e,this.attribute=r}});var ye=w(Y=>{"use strict";f();p();d();var Sn=0;Y.boolean=re();Y.booleanish=re();Y.overloadedBoolean=re();Y.number=re();Y.spaceSeparated=re();Y.commaSeparated=re();Y.commaOrSpaceSeparated=re();function re(){return Math.pow(2,++Sn)}});var Ee=w((Il,Ze)=>{"use strict";f();p();d();var Ye=Ae(),Xe=ye();Ze.exports=Pe;Pe.prototype=new Ye;Pe.prototype.defined=!0;var Qe=["boolean","booleanish","overloadedBoolean","number","commaSeparated","spaceSeparated","commaOrSpaceSeparated"],qn=Qe.length;function Pe(e,r,n,o){var a=-1,g;for(Je(this,"space",o),Ye.call(this,e,r);++a<qn;)g=Qe[a],Je(this,g,(n&Xe[g])===Xe[g])}function Je(e,r,n){n&&(e[r]=n)}});var te=w((Ul,er)=>{"use strict";f();p();d();var _e=me(),An=qe(),Pn=Ee();er.exports=En;function En(e){var r=e.space,n=e.mustUseProperty||[],o=e.attributes||{},a=e.properties,g=e.transform,b={},E={},m,M;for(m in a)M=new Pn(m,g(o,m),a[m],r),n.indexOf(m)!==-1&&(M.mustUseProperty=!0),b[m]=M,E[_e(m)]=m,E[_e(M.attribute)]=m;return new An(b,E,r)}});var nr=w((Hl,rr)=>{"use strict";f();p();d();var Ln=te();rr.exports=Ln({space:"xlink",transform:kn,properties:{xLinkActuate:null,xLinkArcRole:null,xLinkHref:null,xLinkRole:null,xLinkShow:null,xLinkTitle:null,xLinkType:null}});function kn(e,r){return"xlink:"+r.slice(5).toLowerCase()}});var lr=w((Gl,ar)=>{"use strict";f();p();d();var Tn=te();ar.exports=Tn({space:"xml",transform:Mn,properties:{xmlLang:null,xmlBase:null,xmlSpace:null}});function Mn(e,r){return"xml:"+r.slice(3).toLowerCase()}});var ir=w((Jl,tr)=>{"use strict";f();p();d();tr.exports=On;function On(e,r){return r in e?e[r]:r}});var Le=w((_l,or)=>{"use strict";f();p();d();var In=ir();or.exports=Dn;function Dn(e,r){return In(e,r.toLowerCase())}});var sr=w((at,ur)=>{"use strict";f();p();d();var Nn=te(),Rn=Le();ur.exports=Nn({space:"xmlns",attributes:{xmlnsxlink:"xmlns:xlink"},transform:Rn,properties:{xmlns:null,xmlnsXLink:null}})});var fr=w((ot,cr)=>{"use strict";f();p();d();var ke=ye(),Un=te(),j=ke.booleanish,F=ke.number,ne=ke.spaceSeparated;cr.exports=Un({transform:jn,properties:{ariaActiveDescendant:null,ariaAtomic:j,ariaAutoComplete:null,ariaBusy:j,ariaChecked:j,ariaColCount:F,ariaColIndex:F,ariaColSpan:F,ariaControls:ne,ariaCurrent:null,ariaDescribedBy:ne,ariaDetails:null,ariaDisabled:j,ariaDropEffect:ne,ariaErrorMessage:null,ariaExpanded:j,ariaFlowTo:ne,ariaGrabbed:j,ariaHasPopup:null,ariaHidden:j,ariaInvalid:null,ariaKeyShortcuts:null,ariaLabel:null,ariaLabelledBy:ne,ariaLevel:F,ariaLive:null,ariaModal:j,ariaMultiLine:j,ariaMultiSelectable:j,ariaOrientation:null,ariaOwns:ne,ariaPlaceholder:null,ariaPosInSet:F,ariaPressed:j,ariaReadOnly:j,ariaRelevant:null,ariaRequired:j,ariaRoleDescription:ne,ariaRowCount:F,ariaRowIndex:F,ariaRowSpan:F,ariaSelected:j,ariaSetSize:F,ariaSort:null,ariaValueMax:F,ariaValueMin:F,ariaValueNow:F,ariaValueText:null,role:null}});function jn(e,r){return r==="role"?r:"aria-"+r.slice(4).toLowerCase()}});var pr=w((ft,dr)=>{"use strict";f();p();d();var ie=ye(),zn=te(),Bn=Le(),h=ie.boolean,Hn=ie.overloadedBoolean,de=ie.booleanish,k=ie.number,U=ie.spaceSeparated,xe=ie.commaSeparated;dr.exports=zn({space:"html",attributes:{acceptcharset:"accept-charset",classname:"class",htmlfor:"for",httpequiv:"http-equiv"},transform:Bn,mustUseProperty:["checked","multiple","muted","selected"],properties:{abbr:null,accept:xe,acceptCharset:U,accessKey:U,action:null,allow:null,allowFullScreen:h,allowPaymentRequest:h,allowUserMedia:h,alt:null,as:null,async:h,autoCapitalize:null,autoComplete:U,autoFocus:h,autoPlay:h,capture:h,charSet:null,checked:h,cite:null,className:U,cols:k,colSpan:null,content:null,contentEditable:de,controls:h,controlsList:U,coords:k|xe,crossOrigin:null,data:null,dateTime:null,decoding:null,default:h,defer:h,dir:null,dirName:null,disabled:h,download:Hn,draggable:de,encType:null,enterKeyHint:null,form:null,formAction:null,formEncType:null,formMethod:null,formNoValidate:h,formTarget:null,headers:U,height:k,hidden:h,high:k,href:null,hrefLang:null,htmlFor:U,httpEquiv:U,id:null,imageSizes:null,imageSrcSet:xe,inputMode:null,integrity:null,is:null,isMap:h,itemId:null,itemProp:U,itemRef:U,itemScope:h,itemType:U,kind:null,label:null,lang:null,language:null,list:null,loading:null,loop:h,low:k,manifest:null,max:null,maxLength:k,media:null,method:null,min:null,minLength:k,multiple:h,muted:h,name:null,nonce:null,noModule:h,noValidate:h,onAbort:null,onAfterPrint:null,onAuxClick:null,onBeforePrint:null,onBeforeUnload:null,onBlur:null,onCancel:null,onCanPlay:null,onCanPlayThrough:null,onChange:null,onClick:null,onClose:null,onContextMenu:null,onCopy:null,onCueChange:null,onCut:null,onDblClick:null,onDrag:null,onDragEnd:null,onDragEnter:null,onDragExit:null,onDragLeave:null,onDragOver:null,onDragStart:null,onDrop:null,onDurationChange:null,onEmptied:null,onEnded:null,onError:null,onFocus:null,onFormData:null,onHashChange:null,onInput:null,onInvalid:null,onKeyDown:null,onKeyPress:null,onKeyUp:null,onLanguageChange:null,onLoad:null,onLoadedData:null,onLoadedMetadata:null,onLoadEnd:null,onLoadStart:null,onMessage:null,onMessageError:null,onMouseDown:null,onMouseEnter:null,onMouseLeave:null,onMouseMove:null,onMouseOut:null,onMouseOver:null,onMouseUp:null,onOffline:null,onOnline:null,onPageHide:null,onPageShow:null,onPaste:null,onPause:null,onPlay:null,onPlaying:null,onPopState:null,onProgress:null,onRateChange:null,onRejectionHandled:null,onReset:null,onResize:null,onScroll:null,onSecurityPolicyViolation:null,onSeeked:null,onSeeking:null,onSelect:null,onSlotChange:null,onStalled:null,onStorage:null,onSubmit:null,onSuspend:null,onTimeUpdate:null,onToggle:null,onUnhandledRejection:null,onUnload:null,onVolumeChange:null,onWaiting:null,onWheel:null,open:h,optimum:k,pattern:null,ping:U,placeholder:null,playsInline:h,poster:null,preload:null,readOnly:h,referrerPolicy:null,rel:U,required:h,reversed:h,rows:k,rowSpan:k,sandbox:U,scope:null,scoped:h,seamless:h,selected:h,shape:null,size:k,sizes:null,slot:null,span:k,spellCheck:de,src:null,srcDoc:null,srcLang:null,srcSet:xe,start:k,step:null,style:null,tabIndex:k,target:null,title:null,translate:null,type:null,typeMustMatch:h,useMap:null,value:de,width:k,wrap:null,align:null,aLink:null,archive:U,axis:null,background:null,bgColor:null,border:k,borderColor:null,bottomMargin:k,cellPadding:null,cellSpacing:null,char:null,charOff:null,classId:null,clear:null,code:null,codeBase:null,codeType:null,color:null,compact:h,declare:h,event:null,face:null,frame:null,frameBorder:null,hSpace:k,leftMargin:k,link:null,longDesc:null,lowSrc:null,marginHeight:k,marginWidth:k,noResize:h,noHref:h,noShade:h,noWrap:h,object:null,profile:null,prompt:null,rev:null,rightMargin:k,rules:null,scheme:null,scrolling:de,standby:null,summary:null,text:null,topMargin:k,valueType:null,version:null,vAlign:null,vLink:null,vSpace:k,allowTransparency:null,autoCorrect:null,autoSave:null,disablePictureInPicture:h,disableRemotePlayback:h,prefix:null,property:null,results:k,security:null,unselectable:null}})});var vr=w((vt,gr)=>{"use strict";f();p();d();var Wn=Ve(),Fn=nr(),Vn=lr(),Gn=sr(),Kn=fr(),$n=pr();gr.exports=Wn([Vn,Fn,Gn,Kn,$n])});var yr=w((xt,mr)=>{"use strict";f();p();d();var Xn=me(),Jn=Ee(),Yn=Ae(),Te="data";mr.exports=_n;var Qn=/^data[-\w.:]+$/i,hr=/-[a-z]/g,Zn=/[A-Z]/g;function _n(e,r){var n=Xn(r),o=r,a=Yn;return n in e.normal?e.property[e.normal[n]]:(n.length>4&&n.slice(0,4)===Te&&Qn.test(r)&&(r.charAt(4)==="-"?o=ea(r):r=ra(r),a=Jn),new a(o,r))}function ea(e){var r=e.slice(5).replace(hr,aa);return Te+r.charAt(0).toUpperCase()+r.slice(1)}function ra(e){var r=e.slice(4);return hr.test(r)?e:(r=r.replace(Zn,na),r.charAt(0)!=="-"&&(r="-"+r),Te+r)}function na(e){return"-"+e.toLowerCase()}function aa(e){return e.charAt(1).toUpperCase()}});var wr=w((St,br)=>{"use strict";f();p();d();br.exports=la;var xr=/[#.]/g;function la(e,r){for(var n=e||"",o=r||"div",a={},g=0,b,E,m;g<n.length;)xr.lastIndex=g,m=xr.exec(n),b=n.slice(g,m?m.index:n.length),b&&(E?E==="#"?a.id=b:a.className?a.className.push(b):a.className=[b]:o=b,g+=b.length),m&&(E=m[0],g++);return{type:"element",tagName:o,properties:a,children:[]}}});var Sr=w(Me=>{"use strict";f();p();d();Me.parse=oa;Me.stringify=ua;var Cr="",ta=" ",ia=/[ \t\n\r\f]+/g;function oa(e){var r=String(e||Cr).trim();return r===Cr?[]:r.split(ia)}function ua(e){return e.join(ta).trim()}});var Ar=w(Ie=>{"use strict";f();p();d();Ie.parse=sa;Ie.stringify=ca;var Oe=",",qr=" ",pe="";function sa(e){for(var r=[],n=String(e||pe),o=n.indexOf(Oe),a=0,g=!1,b;!g;)o===-1&&(o=n.length,g=!0),b=n.slice(a,o).trim(),(b||!g)&&r.push(b),a=o+1,o=n.indexOf(Oe,a);return r}function ca(e,r){var n=r||{},o=n.padLeft===!1?pe:qr,a=n.padRight?qr:pe;return e[e.length-1]===pe&&(e=e.concat(pe)),e.join(a+Oe+o).trim()}});var Or=w((Nt,Mr)=>{"use strict";f();p();d();var fa=yr(),Pr=me(),da=wr(),Er=Sr().parse,Lr=Ar().parse;Mr.exports=ga;var pa={}.hasOwnProperty;function ga(e,r,n){var o=n?xa(n):null;return a;function a(b,E){var m=da(b,r),M=Array.prototype.slice.call(arguments,2),R=m.tagName.toLowerCase(),O;if(m.tagName=o&&pa.call(o,R)?o[R]:R,E&&va(E,m)&&(M.unshift(E),E=null),E)for(O in E)g(m.properties,O,E[O]);return Tr(m.children,M),m.tagName==="template"&&(m.content={type:"root",children:m.children},m.children=[]),m}function g(b,E,m){var M,R,O;m==null||m!==m||(M=fa(e,E),R=M.property,O=m,typeof O=="string"&&(M.spaceSeparated?O=Er(O):M.commaSeparated?O=Lr(O):M.commaOrSpaceSeparated&&(O=Er(Lr(O).join(" ")))),R==="style"&&typeof m!="string"&&(O=ya(O)),R==="className"&&b.className&&(O=b.className.concat(O)),b[R]=ma(M,R,O))}}function va(e,r){return typeof e=="string"||"length"in e||ha(r.tagName,e)}function ha(e,r){var n=r.type;return e==="input"||!n||typeof n!="string"?!1:typeof r.children=="object"&&"length"in r.children?!0:(n=n.toLowerCase(),e==="button"?n!=="menu"&&n!=="submit"&&n!=="reset"&&n!=="button":"value"in r)}function Tr(e,r){var n,o;if(typeof r=="string"||typeof r=="number"){e.push({type:"text",value:String(r)});return}if(typeof r=="object"&&"length"in r){for(n=-1,o=r.length;++n<o;)Tr(e,r[n]);return}if(typeof r!="object"||!("type"in r))throw new Error("Expected node, nodes, or string, got `"+r+"`");e.push(r)}function ma(e,r,n){var o,a,g;if(typeof n!="object"||!("length"in n))return kr(e,r,n);for(a=n.length,o=-1,g=[];++o<a;)g[o]=kr(e,r,n[o]);return g}function kr(e,r,n){var o=n;return e.number||e.positiveNumber?!isNaN(o)&&o!==""&&(o=Number(o)):(e.boolean||e.overloadedBoolean)&&typeof o=="string"&&(o===""||Pr(n)===Pr(r))&&(o=!0),o}function ya(e){var r=[],n;for(n in e)r.push([n,e[n]].join(": "));return r.join("; ")}function xa(e){for(var r=e.length,n=-1,o={},a;++n<r;)a=e[n],o[a.toLowerCase()]=a;return o}});var Nr=w((zt,Dr)=>{"use strict";f();p();d();var ba=vr(),wa=Or(),Ir=wa(ba,"div");Ir.displayName="html";Dr.exports=Ir});var Ur=w((Ft,Rr)=>{"use strict";f();p();d();Rr.exports=Nr()});var jr=w(($t,Ca)=>{Ca.exports={AElig:"\xC6",AMP:"&",Aacute:"\xC1",Acirc:"\xC2",Agrave:"\xC0",Aring:"\xC5",Atilde:"\xC3",Auml:"\xC4",COPY:"\xA9",Ccedil:"\xC7",ETH:"\xD0",Eacute:"\xC9",Ecirc:"\xCA",Egrave:"\xC8",Euml:"\xCB",GT:">",Iacute:"\xCD",Icirc:"\xCE",Igrave:"\xCC",Iuml:"\xCF",LT:"<",Ntilde:"\xD1",Oacute:"\xD3",Ocirc:"\xD4",Ograve:"\xD2",Oslash:"\xD8",Otilde:"\xD5",Ouml:"\xD6",QUOT:'"',REG:"\xAE",THORN:"\xDE",Uacute:"\xDA",Ucirc:"\xDB",Ugrave:"\xD9",Uuml:"\xDC",Yacute:"\xDD",aacute:"\xE1",acirc:"\xE2",acute:"\xB4",aelig:"\xE6",agrave:"\xE0",amp:"&",aring:"\xE5",atilde:"\xE3",auml:"\xE4",brvbar:"\xA6",ccedil:"\xE7",cedil:"\xB8",cent:"\xA2",copy:"\xA9",curren:"\xA4",deg:"\xB0",divide:"\xF7",eacute:"\xE9",ecirc:"\xEA",egrave:"\xE8",eth:"\xF0",euml:"\xEB",frac12:"\xBD",frac14:"\xBC",frac34:"\xBE",gt:">",iacute:"\xED",icirc:"\xEE",iexcl:"\xA1",igrave:"\xEC",iquest:"\xBF",iuml:"\xEF",laquo:"\xAB",lt:"<",macr:"\xAF",micro:"\xB5",middot:"\xB7",nbsp:"\xA0",not:"\xAC",ntilde:"\xF1",oacute:"\xF3",ocirc:"\xF4",ograve:"\xF2",ordf:"\xAA",ordm:"\xBA",oslash:"\xF8",otilde:"\xF5",ouml:"\xF6",para:"\xB6",plusmn:"\xB1",pound:"\xA3",quot:'"',raquo:"\xBB",reg:"\xAE",sect:"\xA7",shy:"\xAD",sup1:"\xB9",sup2:"\xB2",sup3:"\xB3",szlig:"\xDF",thorn:"\xFE",times:"\xD7",uacute:"\xFA",ucirc:"\xFB",ugrave:"\xF9",uml:"\xA8",uuml:"\xFC",yacute:"\xFD",yen:"\xA5",yuml:"\xFF"}});var zr=w((Xt,Sa)=>{Sa.exports={"0":"\uFFFD","128":"\u20AC","130":"\u201A","131":"\u0192","132":"\u201E","133":"\u2026","134":"\u2020","135":"\u2021","136":"\u02C6","137":"\u2030","138":"\u0160","139":"\u2039","140":"\u0152","142":"\u017D","145":"\u2018","146":"\u2019","147":"\u201C","148":"\u201D","149":"\u2022","150":"\u2013","151":"\u2014","152":"\u02DC","153":"\u2122","154":"\u0161","155":"\u203A","156":"\u0153","158":"\u017E","159":"\u0178"}});var De=w((Jt,Br)=>{"use strict";f();p();d();Br.exports=qa;function qa(e){var r=typeof e=="string"?e.charCodeAt(0):e;return r>=48&&r<=57}});var Wr=w((_t,Hr)=>{"use strict";f();p();d();Hr.exports=Aa;function Aa(e){var r=typeof e=="string"?e.charCodeAt(0):e;return r>=97&&r<=102||r>=65&&r<=70||r>=48&&r<=57}});var Vr=w((ai,Fr)=>{"use strict";f();p();d();Fr.exports=Pa;function Pa(e){var r=typeof e=="string"?e.charCodeAt(0):e;return r>=97&&r<=122||r>=65&&r<=90}});var Kr=w((oi,Gr)=>{"use strict";f();p();d();var Ea=Vr(),La=De();Gr.exports=ka;function ka(e){return Ea(e)||La(e)}});var on=w((fi,tn)=>{"use strict";f();p();d();var $r=jr(),Xr=zr(),Ta=De(),Ma=Wr(),Zr=Kr(),Oa=xn();tn.exports=Ga;var Ia={}.hasOwnProperty,oe=String.fromCharCode,Da=Function.prototype,Jr={warning:null,reference:null,text:null,warningContext:null,referenceContext:null,textContext:null,position:{},additional:null,attribute:!1,nonTerminated:!0},Na=9,Yr=10,Ra=12,Ua=32,Qr=38,ja=59,za=60,Ba=61,Ha=35,Wa=88,Fa=120,Va=65533,ue="named",Re="hexadecimal",Ue="decimal",je={};je[Re]=16;je[Ue]=10;var be={};be[ue]=Zr;be[Ue]=Ta;be[Re]=Ma;var _r=1,en=2,rn=3,nn=4,an=5,Ne=6,ln=7,Q={};Q[_r]="Named character references must be terminated by a semicolon";Q[en]="Numeric character references must be terminated by a semicolon";Q[rn]="Named character references cannot be empty";Q[nn]="Numeric character references cannot be empty";Q[an]="Named character references must be known";Q[Ne]="Numeric character references cannot be disallowed";Q[ln]="Numeric character references cannot be outside the permissible Unicode range";function Ga(e,r){var n={},o,a;r||(r={});for(a in Jr)o=r[a],n[a]=o??Jr[a];return(n.position.indent||n.position.start)&&(n.indent=n.position.indent||[],n.position=n.position.start),Ka(e,n)}function Ka(e,r){var n=r.additional,o=r.nonTerminated,a=r.text,g=r.reference,b=r.warning,E=r.textContext,m=r.referenceContext,M=r.warningContext,R=r.position,O=r.indent||[],K=e.length,B=0,se=-1,t=R.column||1,l=R.line||1,i="",u=[],s,v,x,c,L,y,C,z,Z,ce,$,J,T,I,X,G,N,H,P;for(typeof n=="string"&&(n=n.charCodeAt(0)),G=V(),z=b?ae:Da,B--,K++;++B<K;)if(L===Yr&&(t=O[se]||1),L=e.charCodeAt(B),L===Qr){if(C=e.charCodeAt(B+1),C===Na||C===Yr||C===Ra||C===Ua||C===Qr||C===za||C!==C||n&&C===n){i+=oe(L),t++;continue}for(T=B+1,J=T,P=T,C===Ha?(P=++J,C=e.charCodeAt(P),C===Wa||C===Fa?(I=Re,P=++J):I=Ue):I=ue,s="",$="",c="",X=be[I],P--;++P<K&&(C=e.charCodeAt(P),!!X(C));)c+=oe(C),I===ue&&Ia.call($r,c)&&(s=c,$=$r[c]);x=e.charCodeAt(P)===ja,x&&(P++,v=I===ue?Oa(c):!1,v&&(s=c,$=v)),H=1+P-T,!x&&!o||(c?I===ue?(x&&!$?z(an,1):(s!==c&&(P=J+s.length,H=1+P-J,x=!1),x||(Z=s?_r:rn,r.attribute?(C=e.charCodeAt(P),C===Ba?(z(Z,H),$=null):Zr(C)?$=null:z(Z,H)):z(Z,H))),y=$):(x||z(en,H),y=parseInt(c,je[I]),$a(y)?(z(ln,H),y=oe(Va)):y in Xr?(z(Ne,H),y=Xr[y]):(ce="",Xa(y)&&z(Ne,H),y>65535&&(y-=65536,ce+=oe(y>>>10|55296),y=56320|y&1023),y=ce+oe(y))):I!==ue&&z(nn,H)),y?(_(),G=V(),B=P-1,t+=P-T+1,u.push(y),N=V(),N.offset++,g&&g.call(m,y,{start:G,end:N},e.slice(T-1,P)),G=N):(c=e.slice(T-1,P),i+=c,t+=c.length,B=P-1)}else L===10&&(l++,se++,t=0),L===L?(i+=oe(L),t++):_();return u.join("");function V(){return{line:l,column:t,offset:B+(R.offset||0)}}function ae(le,fe){var ee=V();ee.column+=fe,ee.offset+=fe,b.call(M,Q[le],ee,le)}function _(){i&&(u.push(i),a&&a.call(E,i,{start:G,end:V()}),i="")}}function $a(e){return e>=55296&&e<=57343||e>1114111}function Xa(e){return e>=1&&e<=8||e===11||e>=13&&e<=31||e>=127&&e<=159||e>=64976&&e<=65007||(e&65535)===65535||(e&65535)===65534}});var sn=w((vi,we)=>{"use strict";f();p();d();var Ja=typeof window<"u"?window:typeof WorkerGlobalScope<"u"&&self instanceof WorkerGlobalScope?self:{};var un=function(e){var r=/(?:^|\s)lang(?:uage)?-([\w-]+)(?=\s|$)/i,n=0,o={},a={manual:e.Prism&&e.Prism.manual,disableWorkerMessageHandler:e.Prism&&e.Prism.disableWorkerMessageHandler,util:{encode:function t(l){return l instanceof g?new g(l.type,t(l.content),l.alias):Array.isArray(l)?l.map(t):l.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/\u00a0/g," ")},type:function(t){return Object.prototype.toString.call(t).slice(8,-1)},objId:function(t){return t.__id||Object.defineProperty(t,"__id",{value:++n}),t.__id},clone:function t(l,i){i=i||{};var u,s;switch(a.util.type(l)){case"Object":if(s=a.util.objId(l),i[s])return i[s];u={},i[s]=u;for(var v in l)l.hasOwnProperty(v)&&(u[v]=t(l[v],i));return u;case"Array":return s=a.util.objId(l),i[s]?i[s]:(u=[],i[s]=u,l.forEach(function(x,c){u[c]=t(x,i)}),u);default:return l}},getLanguage:function(t){for(;t;){var l=r.exec(t.className);if(l)return l[1].toLowerCase();t=t.parentElement}return"none"},setLanguage:function(t,l){t.className=t.className.replace(RegExp(r,"gi"),""),t.classList.add("language-"+l)},currentScript:function(){if(typeof document>"u")return null;if("currentScript"in document)return document.currentScript;try{throw new Error}catch(u){var t=(/at [^(\r\n]*\((.*):[^:]+:[^:]+\)$/i.exec(u.stack)||[])[1];if(t){var l=document.getElementsByTagName("script");for(var i in l)if(l[i].src==t)return l[i]}return null}},isActive:function(t,l,i){for(var u="no-"+l;t;){var s=t.classList;if(s.contains(l))return!0;if(s.contains(u))return!1;t=t.parentElement}return!!i}},languages:{plain:o,plaintext:o,text:o,txt:o,extend:function(t,l){var i=a.util.clone(a.languages[t]);for(var u in l)i[u]=l[u];return i},insertBefore:function(t,l,i,u){u=u||a.languages;var s=u[t],v={};for(var x in s)if(s.hasOwnProperty(x)){if(x==l)for(var c in i)i.hasOwnProperty(c)&&(v[c]=i[c]);i.hasOwnProperty(x)||(v[x]=s[x])}var L=u[t];return u[t]=v,a.languages.DFS(a.languages,function(y,C){C===L&&y!=t&&(this[y]=v)}),v},DFS:function t(l,i,u,s){s=s||{};var v=a.util.objId;for(var x in l)if(l.hasOwnProperty(x)){i.call(l,x,l[x],u||x);var c=l[x],L=a.util.type(c);L==="Object"&&!s[v(c)]?(s[v(c)]=!0,t(c,i,null,s)):L==="Array"&&!s[v(c)]&&(s[v(c)]=!0,t(c,i,x,s))}}},plugins:{},highlightAll:function(t,l){a.highlightAllUnder(document,t,l)},highlightAllUnder:function(t,l,i){var u={callback:i,container:t,selector:'code[class*="language-"], [class*="language-"] code, code[class*="lang-"], [class*="lang-"] code'};a.hooks.run("before-highlightall",u),u.elements=Array.prototype.slice.apply(u.container.querySelectorAll(u.selector)),a.hooks.run("before-all-elements-highlight",u);for(var s=0,v;v=u.elements[s++];)a.highlightElement(v,l===!0,u.callback)},highlightElement:function(t,l,i){var u=a.util.getLanguage(t),s=a.languages[u];a.util.setLanguage(t,u);var v=t.parentElement;v&&v.nodeName.toLowerCase()==="pre"&&a.util.setLanguage(v,u);var x=t.textContent,c={element:t,language:u,grammar:s,code:x};function L(C){c.highlightedCode=C,a.hooks.run("before-insert",c),c.element.innerHTML=c.highlightedCode,a.hooks.run("after-highlight",c),a.hooks.run("complete",c),i&&i.call(c.element)}if(a.hooks.run("before-sanity-check",c),v=c.element.parentElement,v&&v.nodeName.toLowerCase()==="pre"&&!v.hasAttribute("tabindex")&&v.setAttribute("tabindex","0"),!c.code){a.hooks.run("complete",c),i&&i.call(c.element);return}if(a.hooks.run("before-highlight",c),!c.grammar){L(a.util.encode(c.code));return}if(l&&e.Worker){var y=new Worker(a.filename);y.onmessage=function(C){L(C.data)},y.postMessage(JSON.stringify({language:c.language,code:c.code,immediateClose:!0}))}else L(a.highlight(c.code,c.grammar,c.language))},highlight:function(t,l,i){var u={code:t,grammar:l,language:i};if(a.hooks.run("before-tokenize",u),!u.grammar)throw new Error('The language "'+u.language+'" has no grammar.');return u.tokens=a.tokenize(u.code,u.grammar),a.hooks.run("after-tokenize",u),g.stringify(a.util.encode(u.tokens),u.language)},tokenize:function(t,l){var i=l.rest;if(i){for(var u in i)l[u]=i[u];delete l.rest}var s=new m;return M(s,s.head,t),E(t,s,l,s.head,0),O(s)},hooks:{all:{},add:function(t,l){var i=a.hooks.all;i[t]=i[t]||[],i[t].push(l)},run:function(t,l){var i=a.hooks.all[t];if(!(!i||!i.length))for(var u=0,s;s=i[u++];)s(l)}},Token:g};e.Prism=a;function g(t,l,i,u){this.type=t,this.content=l,this.alias=i,this.length=(u||"").length|0}g.stringify=function t(l,i){if(typeof l=="string")return l;if(Array.isArray(l)){var u="";return l.forEach(function(L){u+=t(L,i)}),u}var s={type:l.type,content:t(l.content,i),tag:"span",classes:["token",l.type],attributes:{},language:i},v=l.alias;v&&(Array.isArray(v)?Array.prototype.push.apply(s.classes,v):s.classes.push(v)),a.hooks.run("wrap",s);var x="";for(var c in s.attributes)x+=" "+c+'="'+(s.attributes[c]||"").replace(/"/g,"&quot;")+'"';return"<"+s.tag+' class="'+s.classes.join(" ")+'"'+x+">"+s.content+"</"+s.tag+">"};function b(t,l,i,u){t.lastIndex=l;var s=t.exec(i);if(s&&u&&s[1]){var v=s[1].length;s.index+=v,s[0]=s[0].slice(v)}return s}function E(t,l,i,u,s,v){for(var x in i)if(!(!i.hasOwnProperty(x)||!i[x])){var c=i[x];c=Array.isArray(c)?c:[c];for(var L=0;L<c.length;++L){if(v&&v.cause==x+","+L)return;var y=c[L],C=y.inside,z=!!y.lookbehind,Z=!!y.greedy,ce=y.alias;if(Z&&!y.pattern.global){var $=y.pattern.toString().match(/[imsuy]*$/)[0];y.pattern=RegExp(y.pattern.source,$+"g")}for(var J=y.pattern||y,T=u.next,I=s;T!==l.tail&&!(v&&I>=v.reach);I+=T.value.length,T=T.next){var X=T.value;if(l.length>t.length)return;if(!(X instanceof g)){var G=1,N;if(Z){if(N=b(J,I,t,z),!N||N.index>=t.length)break;var ae=N.index,H=N.index+N[0].length,P=I;for(P+=T.value.length;ae>=P;)T=T.next,P+=T.value.length;if(P-=T.value.length,I=P,T.value instanceof g)continue;for(var V=T;V!==l.tail&&(P<H||typeof V.value=="string");V=V.next)G++,P+=V.value.length;G--,X=t.slice(I,P),N.index-=I}else if(N=b(J,0,X,z),!N)continue;var ae=N.index,_=N[0],le=X.slice(0,ae),fe=X.slice(ae+_.length),ee=I+X.length;v&&ee>v.reach&&(v.reach=ee);var he=T.prev;le&&(he=M(l,he,le),I+=le.length),R(l,he,G);var pn=new g(x,C?a.tokenize(_,C):_,ce,_);if(T=M(l,he,pn),fe&&M(l,T,fe),G>1){var Ce={cause:x+","+L,reach:ee};E(t,l,i,T.prev,I,Ce),v&&Ce.reach>v.reach&&(v.reach=Ce.reach)}}}}}}function m(){var t={value:null,prev:null,next:null},l={value:null,prev:t,next:null};t.next=l,this.head=t,this.tail=l,this.length=0}function M(t,l,i){var u=l.next,s={value:i,prev:l,next:u};return l.next=s,u.prev=s,t.length++,s}function R(t,l,i){for(var u=l.next,s=0;s<i&&u!==t.tail;s++)u=u.next;l.next=u,u.prev=l,t.length-=s}function O(t){for(var l=[],i=t.head.next;i!==t.tail;)l.push(i.value),i=i.next;return l}if(!e.document)return e.addEventListener&&(a.disableWorkerMessageHandler||e.addEventListener("message",function(t){var l=JSON.parse(t.data),i=l.language,u=l.code,s=l.immediateClose;e.postMessage(a.highlight(u,a.languages[i],i)),s&&e.close()},!1)),a;var K=a.util.currentScript();K&&(a.filename=K.src,K.hasAttribute("data-manual")&&(a.manual=!0));function B(){a.manual||a.highlightAll()}if(!a.manual){var se=document.readyState;se==="loading"||se==="interactive"&&K&&K.defer?document.addEventListener("DOMContentLoaded",B):window.requestAnimationFrame?window.requestAnimationFrame(B):window.setTimeout(B,16)}return a}(Ja);typeof we<"u"&&we.exports&&(we.exports=un);typeof globalThis<"u"&&(globalThis.Prism=un)});var dl=w((xi,dn)=>{f();p();d();var ge=typeof globalThis=="object"?globalThis:typeof self=="object"?self:typeof window=="object"?window:typeof globalThis=="object"?globalThis:{},Ya=fl();ge.Prism={manual:!0,disableWorkerMessageHandler:!0};var Qa=Ur(),Za=on(),cn=sn(),_a=mn(),el=vn(),rl=gn(),nl=hn();Ya();var ze={}.hasOwnProperty;function fn(){}fn.prototype=cn;var D=new fn;dn.exports=D;D.highlight=ll;D.register=ve;D.alias=al;D.registered=tl;D.listLanguages=il;ve(_a);ve(el);ve(rl);ve(nl);D.util.encode=sl;D.Token.stringify=ol;function ve(e){if(typeof e!="function"||!e.displayName)throw new Error("Expected `function` for `grammar`, got `"+e+"`");D.languages[e.displayName]===void 0&&e(D)}function al(e,r){var n=D.languages,o=e,a,g,b,E;r&&(o={},o[e]=r);for(a in o)for(g=o[a],g=typeof g=="string"?[g]:g,b=g.length,E=-1;++E<b;)n[g[E]]=n[a]}function ll(e,r){var n=cn.highlight,o;if(typeof e!="string")throw new Error("Expected `string` for `value`, got `"+e+"`");if(D.util.type(r)==="Object")o=r,r=null;else{if(typeof r!="string")throw new Error("Expected `string` for `name`, got `"+r+"`");if(ze.call(D.languages,r))o=D.languages[r];else throw new Error("Unknown language: `"+r+"` is not registered")}return n.call(this,e,o,r)}function tl(e){if(typeof e!="string")throw new Error("Expected `string` for `language`, got `"+e+"`");return ze.call(D.languages,e)}function il(){var e=D.languages,r=[],n;for(n in e)ze.call(e,n)&&typeof e[n]=="object"&&r.push(n);return r}function ol(e,r,n){var o;return typeof e=="string"?{type:"text",value:e}:D.util.type(e)==="Array"?ul(e,r):(o={type:e.type,content:D.Token.stringify(e.content,r,n),tag:"span",classes:["token",e.type],attributes:{},language:r,parent:n},e.alias&&(o.classes=o.classes.concat(e.alias)),D.hooks.run("wrap",o),Qa(o.tag+"."+o.classes.join("."),cl(o.attributes),o.content))}function ul(e,r){for(var n=[],o=e.length,a=-1,g;++a<o;)g=e[a],g!==""&&g!==null&&g!==void 0&&n.push(g);for(a=-1,o=n.length;++a<o;)g=n[a],n[a]=D.Token.stringify(g,r,n);return n}function sl(e){return e}function cl(e){var r;for(r in e)e[r]=Za(e[r]);return e}function fl(){var e="Prism"in ge,r=e?ge.Prism:void 0;return n;function n(){e?ge.Prism=r:delete ge.Prism,e=void 0,r=void 0}}});export{dl as a};
/*! Bundled license information:

prismjs/components/prism-core.js:
  (**
   * Prism: Lightweight, robust, elegant syntax highlighting
   *
   * @license MIT <https://opensource.org/licenses/MIT>
   * @author Lea Verou <https://lea.verou.me>
   * @namespace
   * @public
   *)
*/
//# sourceMappingURL=/static/chunk-5IXDT5IB.js.map

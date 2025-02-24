import{Do as s,Hg as c,Ne as n,Sd as i,Ta as a,a as E,f as v,r as l,vo as F}from"/static/chunk-RFJTZKD6.js";import"/static/chunk-XPJ4MQJV.js";import{a as C}from"/static/chunk-3UDJFOQH.js";import"/static/chunk-HHT4SG7V.js";import"/static/chunk-K7LQKAJG.js";import"/static/chunk-QQTK3LZH.js";import"/static/chunk-IJQNM355.js";import"/static/chunk-4CN6THWS.js";import"/static/chunk-272RTCFX.js";import"/static/chunk-2ROB4QWU.js";import"/static/chunk-ALT2ZZSO.js";import"/static/chunk-UE6SLBBN.js";import"/static/chunk-GINZUAUY.js";import"/static/chunk-SQELCOUW.js";import"/static/chunk-IGYUTZ65.js";import"/static/chunk-YM6UBNGD.js";import"/static/chunk-C6TQ5FFZ.js";import"/static/chunk-GXGA523B.js";import"/static/chunk-N4MMWRNK.js";import"/static/chunk-NRLAI7OY.js";import"/static/chunk-LVVHNICT.js";import"/static/chunk-2AXSSSSX.js";import"/static/chunk-DGXQI7RB.js";import"/static/chunk-HUCRWDLX.js";import"/static/chunk-RFEQG3YN.js";import"/static/chunk-PUISI233.js";import{d as r,e as p,g,j as d}from"/static/chunk-SJXEOBQC.js";p();d();g();var t=r(E()),m=r(v());var u=r(C());var o=r(l()),_={component:k},B=`:root {
    --radius: 0px;
}

body[theme=dark] {
    --border: rgba(0, 255, 1, 0.5);
    --link: #00FF01;
    --border-bold: #00FF01;
    --bg-3000: #111;
    --glass-bg-3000: #111;
    --bg-light: #222;
    --bg-table: #222;
    --muted-3000: #0EA70E;
    --primary-3000: #00FF01;
    --primary-3000-hover: #00FF01;
    --primary-alt-highlight: rgba(0, 255, 1, 0.1);
    --text-3000: #00FF01;
    --accent-3000: #222;
    --glass-border-3000: rgba(0,0,0,.3);
    --font-title: ui-monospace, 'Cascadia Code', 'Source Code Pro', Menlo, Consolas, 'DejaVu Sans Mono', monospace;

    --primary-3000-frame-bg-light: #00FF01;
    --primary-3000-button-bg: #00FF01;
    --primary-3000-button-border: #00FF01;
    --text-tertiary: #00FF01;
}

.TopBar3000__content {
	border-bottom: solid 1px #00FF01;
}`,x=`:root {
    --radius: 16px;
}

body[theme=light] {
    --border: rgba(255, 105, 180, 0.5);
    --border-3000: #ff409f;
    --link: #E306AD;
    --border-bold: rgba(255, 105, 180, 0.8);
    --bg-3000: #FED9E9;
    --glass-bg-3000: rgba(255, 192, 203, 0.8);
    --bg-light: #FFF0F5;
    --bg-table: #F8BBD0;
    --muted-3000: #E306AD;
    --primary-3000: #FF69B4;
    --primary-3000-hover: #FF1493;
    --primary-alt-highlight: rgba(255, 105, 180, 0.1);
    --text-3000: #ed3993;
    --text-3000-light: #58003f;
    --accent-3000: #FEBDE2;
    --glass-border-3000: rgba(245, 145, 199, 0.3);

    --primary-3000-frame-bg-light: #F18DBC;
    --primary-3000-button-bg: #FF69B4;
    --primary-3000-button-border: #FF1493;
    --primary-3000-button-border-hover: #db097b;
    --text-tertiary: #FFB6C1;

    --secondary-3000-button-border: #FF1493;
    --secondary-3000-frame-bg-light: #F7B9D7;
    --secondary-3000-button-border-hover: #d40b76;
}`;function k(){let{persistedCustomCss:y,previewingCustomCss:b}=(0,t.useValues)(n),{saveCustomCss:h,setPreviewingCustomCss:e}=(0,t.useActions)(n);return(0,u.useEffect)(()=>{e(b||y||"")},[]),(0,o.jsxs)("div",{className:"flex flex-col space-y-2",children:[(0,o.jsx)(F,{buttons:(0,o.jsxs)(o.Fragment,{children:[(0,o.jsx)(i,{type:"secondary",onClick:()=>{m.router.actions.push(s.projectHomepage())},children:"Preview"}),(0,o.jsx)(i,{type:"primary",onClick:()=>{h(),m.router.actions.push(s.projectHomepage())},children:"Save and set"})]})}),(0,o.jsxs)("p",{children:["You can add custom CSS to change the style of your PostHog instance. If you need some inspiration try our templates: ",(0,o.jsx)(a,{onClick:()=>e(B),children:"Tron"}),","," ",(0,o.jsx)(a,{onClick:()=>e(x),children:"Barbie"})]}),(0,o.jsx)(c,{className:"border",language:"css",value:b||"",onChange:f=>e(f??null),height:600,options:{minimap:{enabled:!1}}})]})}export{k as CustomCssScene,_ as scene};
//# sourceMappingURL=/static/CustomCssScene-BKE2KKZY.js.map

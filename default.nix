let
  pkgs = import <nixpkgs> {};
in
pkgs.mkShell {
  buildInputs = [
    # Required to build psycopg2
    pkgs.openssl

    # Required for frontend build
    pkgs.nodejs-12_x
    pkgs.yarn
    
    # Service dependencies
    pkgs.postgresql 
    pkgs.redis 
    pkgs.apacheKafka];
    
  shellHook = ''
  '';
}
